import argparse

# import os
# import numpy as np
# import math
# from torchvision import datasets
# import torch.nn as nn
# import torch
import torch.nn.functional as F

from torch.utils.data import DataLoader
from torch.autograd import Variable


import copy

from models.cvae import *
from common.dataset import RTdata
from common.filter import *
from common.utils import *
from common.analysis import *
import common.parameter_settings as ps

from common.settings import *

# -----------------------------------------------------------------
#  global  variables
# -----------------------------------------------------------------
parameter_limits = list()
parameter_names_latex = list()


# -----------------------------------------------------------------
#  CUDA available?
# -----------------------------------------------------------------
if torch.cuda.is_available():
    cuda = True
    device = torch.device("cuda")
else:
    cuda = False
    device = torch.device("cpu")

# -----------------------------------------------------------------
#  global FloatTensor instance
# -----------------------------------------------------------------
FloatTensor = torch.cuda.FloatTensor if cuda else torch.FloatTensor


# -----------------------------------------------------------------
#  Loss function
# -----------------------------------------------------------------
def cvae_loss_function(gen_x, real_x, mu, log_var, config):

    """
    Loss function for the CVAE contains two components: 1) MSE to quantify the difference between
    input and output, adn 2) the KLD to force the autoencoder to be more effective, see also
    Appendix B from VAE paper:
    Kingma and Welling. Auto-Encoding Variational Bayes. ICLR, 2014
    https://arxiv.org/abs/1312.6114

    Args:
        gen_x: generated or inferred profile
        real_x: ground truth profile
        mu:   mean
        log_var: log of variance
        config: config object with user supplied parameters

    Returns:
        sum of the two components
    """

    MSE0 = F.mse_loss(input=gen_x, target=real_x.view(-1, config.profile_len), reduction='mean')

    KLD = -0.5 * torch.sum(1 + log_var - mu.pow(2) - log_var.exp())

    return MSE0 + KLD


# -----------------------------------------------------------------
#  Training
# -----------------------------------------------------------------
def cvae_train(model, optimizer, train_loader, config):
    """
    This function trains the network for one epoch.
    Returns: averaged training loss. No need to return the model as the optimizer modifies it inplace.

    Args:
        model: current model state
        optimizer: optimizer object to perform the back-propagation
        train_loader: data loader used for the inference, most likely the test set
        config: config object with user supplied parameters
    """

    if cuda:
        model.cuda()

    model.train()
    train_loss = 0

    for batch_idx, (profiles, parameters) in enumerate(train_loader):

        # configure input
        real_profiles = Variable(profiles.type(FloatTensor))
        real_parameters = Variable(parameters.type(FloatTensor))

        # zero the gradients on each iteration
        optimizer.zero_grad()

        # generate a batch of profiles
        gen_profiles, mu, log_var = model(real_profiles, real_parameters)

        # estimate loss
        loss = cvae_loss_function(gen_profiles, real_profiles, mu, log_var, config)

        train_loss += loss.item()    # average loss per batch

        # back propagation
        loss.backward()
        optimizer.step()

    average_loss = train_loss / len(train_loader)   # divide by number of batches (!= batch size)

    return average_loss  # float


# -----------------------------------------------------------------
#  Validation
# -----------------------------------------------------------------
def cvae_validate(model, val_loader, config):
    """
    This function runs validation data set through the model to prevent over-fitting.
    Returns: averaged validation loss.

    Args:
        model: current model state
        val_loader: data loader used for the inference, here, validation set
        config: config object with user supplied parameters
    """

    if cuda:
        model.cuda()

    model.eval()
    val_loss = 0

    with torch.no_grad():
        for i, (profiles, parameters) in enumerate(val_loader):

            # configure input
            real_profiles = Variable(profiles.type(FloatTensor))
            real_parameters = Variable(parameters.type(FloatTensor))

            # inference
            gen_profiles, mu, log_var = model(real_profiles, real_parameters)

            loss = cvae_loss_function(gen_profiles, real_profiles, mu, log_var, config)

            val_loss += loss.item()    # average loss per batch

    average_loss = val_loss / len(val_loader)   # divide by number of batches (!= batch size)

    return average_loss  # float


# -----------------------------------------------------------------
#  Testing
# -----------------------------------------------------------------
def cvae_test(epoch, test_loader, model, path, config, best_model=False):
    """
    This function runs the test data set through the auto-encoder, saves
    results as well as ground truth to file

    Args:
        epoch: current epoch
        test_loader: data loader used for the inference, most likely the test set
        path: path to output directory
        model: current model state
        config: config object with user supplied parameters
        best_model: flag for testing on best model
    """

    print("\033[94m\033[1mTesting the autoencoder now at epoch %d \033[0m" % epoch)

    if cuda:
        model.cuda()

    model.eval()

    # arrays to store collated results
    test_profiles_gen_all = torch.tensor([], device=device)
    test_profiles_true_all = torch.tensor([], device=device)
    test_parameters_true_all = torch.tensor([], device=device)

    test_loss = 0

    with torch.no_grad():
        for i, (profiles, parameters) in enumerate(test_loader):

            # configure input
            real_profiles = Variable(profiles.type(FloatTensor))
            real_parameters = Variable(parameters.type(FloatTensor))

            gen_profiles, mu, log_var = model(real_profiles, real_parameters)

            loss = cvae_loss_function(gen_profiles, real_profiles, mu, log_var, config)

            test_loss += loss.item()    # average loss per batch

            # collate data
            test_profiles_gen_all = torch.cat((test_profiles_gen_all, gen_profiles), 0)
            test_profiles_true_all = torch.cat((test_profiles_true_all, real_profiles), 0)
            test_parameters_true_all = torch.cat((test_parameters_true_all, real_parameters), 0)

    average_loss = test_loss / len(test_loader)  # divide by number of batches (!= batch size)

    print("[Epoch %d/%d] [Test loss: %e]" % (epoch, config.n_epochs, average_loss))

    # move data to CPU, re-scale parameters, and write everything to file
    test_profiles_gen_all = test_profiles_gen_all.cpu().numpy()
    test_profiles_true_all = test_profiles_true_all.cpu().numpy()
    test_parameters_true_all = test_parameters_true_all.cpu().numpy()

    test_parameters_true_all = utils_rescale_parameters(limits=parameter_limits, parameters=test_parameters_true_all)

    if best_model:
        prefix = 'best'
    else:
        prefix = 'test'

    utils_save_test_data(
        parameters=test_parameters_true_all,
        profiles_true=test_profiles_true_all,
        profiles_gen=test_profiles_gen_all,
        path=path,
        profile_choice=config.profile_type,
        epoch=epoch,
        prefix=prefix
    )


# -----------------------------------------------------------------
#  Main
# -----------------------------------------------------------------
def main(config):

    # -----------------------------------------------------------------
    # create unique output path and run directories, save config
    # -----------------------------------------------------------------
    run_id = 'run_' + utils_get_current_timestamp()
    config.out_dir = os.path.join(config.out_dir, run_id)

    utils_create_run_directories(config.out_dir, DATA_PRODUCTS_DIR, PLOT_DIR)
    utils_save_config_to_log(config)
    utils_save_config_to_file(config)

    data_products_path = os.path.join(config.out_dir, DATA_PRODUCTS_DIR)
    plot_path = os.path.join(config.out_dir, PLOT_DIR)

    # -----------------------------------------------------------------
    # Check if data files exist / read data and shuffle / rescale parameters
    # -----------------------------------------------------------------
    H_profile_file_path = utils_join_path(config.data_dir, H_PROFILE_FILE)
    T_profile_file_path = utils_join_path(config.data_dir, T_PROFILE_FILE)
    global_parameter_file_path = utils_join_path(config.data_dir, GLOBAL_PARAMETER_FILE)

    H_profiles = np.load(H_profile_file_path)
    T_profiles = np.load(T_profile_file_path)
    global_parameters = np.load(global_parameter_file_path)

    # -----------------------------------------------------------------
    # OPTIONAL: Filter (blow-out) profiles
    # -----------------------------------------------------------------
    if config.filter_blowouts:
        H_profiles, T_profiles, global_parameters = filter_blowout_profiles(H_profiles, T_profiles,
                                                                            global_parameters)

    if config.filter_parameters:
        H_profiles, T_profiles, global_parameters = filter_cut_parameter_space(H_profiles, T_profiles,
                                                                               global_parameters)

    # -----------------------------------------------------------------
    # log space?
    # -----------------------------------------------------------------
    if USE_LOG_PROFILES:
        H_profiles = np.log10(H_profiles + 1.0e-6)  # add a small number to avoid trouble
        T_profiles = np.log10(T_profiles)

    # -----------------------------------------------------------------
    # shuffle / rescale parameters
    # -----------------------------------------------------------------
    if SCALE_PARAMETERS:
        global_parameters = utils_scale_parameters(limits=parameter_limits, parameters=global_parameters)

    if SHUFFLE:
        np.random.seed(SHUFFLE_SEED)
        n_samples = H_profiles.shape[0]
        indices = np.arange(n_samples, dtype=np.int32)
        indices = np.random.permutation(indices)
        H_profiles = H_profiles[indices]
        T_profiles = T_profiles[indices]
        global_parameters = global_parameters[indices]

    # -----------------------------------------------------------------
    # we are doing one profile at a time
    # -----------------------------------------------------------------
    if config.profile_type == 'H':
        profiles = H_profiles
    else:
        profiles = T_profiles

    # -----------------------------------------------------------------
    # data loaders
    # -----------------------------------------------------------------
    training_data = RTdata(profiles, global_parameters, split='train', split_frac=SPLIT_FRACTION)
    validation_data = RTdata(profiles, global_parameters, split='val', split_frac=SPLIT_FRACTION)
    testing_data = RTdata(profiles, global_parameters, split='test', split_frac=SPLIT_FRACTION)

    train_loader = DataLoader(training_data, batch_size=config.batch_size, shuffle=True)
    val_loader = DataLoader(validation_data, batch_size=config.batch_size)
    test_loader = DataLoader(testing_data, batch_size=config.batch_size)

    # -----------------------------------------------------------------
    # initialise model + check for CUDA
    # -----------------------------------------------------------------
    if config.model == 'VAE1':
        model = VAE1(config)
    else:
        model = CVAE1(config)

    if cuda:
        model.cuda()

    # -----------------------------------------------------------------
    # Optimizers
    # -----------------------------------------------------------------
    optimizer = torch.optim.Adam(model.parameters(), lr=config.lr, betas=(config.b1, config.b2))

    # -----------------------------------------------------------------
    # book keeping arrays
    # -----------------------------------------------------------------
    train_loss_array = np.empty(0)
    val_loss_array = np.empty(0)

    # -----------------------------------------------------------------
    # keep the model with min validation loss
    # -----------------------------------------------------------------
    best_model = copy.deepcopy(model)
    best_loss = np.inf
    best_epoch = 0

    # -----------------------------------------------------------------
    # Early Stopping Criteria
    # -----------------------------------------------------------------
    n_epoch_without_improvement = 0
    stopped_early = False
    epochs_trained = -1

    # -----------------------------------------------------------------
    #  Main training loop
    # -----------------------------------------------------------------
    print("\033[96m\033[1m\nTraining starts now\033[0m")
    for epoch in range(1, config.n_epochs+1):

        train_loss = cvae_train(model, optimizer, train_loader, config)
        val_loss = cvae_validate(model, val_loader, config)

        train_loss_array = np.append(train_loss_array, train_loss)
        val_loss_array = np.append(val_loss_array, val_loss)

        if val_loss < best_loss:
            best_loss = val_loss
            best_model = copy.deepcopy(model)
            best_epoch = epoch
            n_epoch_without_improvement = 0
        else:
            n_epoch_without_improvement += 1

        print(
            "[Epoch %d/%d] [Train loss: %e] [Validation loss: %e] [Best epoch: %d]"
            % (epoch, config.n_epochs,  train_loss, val_loss, best_epoch)
        )

        # check for testing criterion
        if epoch % config.testing_interval == 0 or epoch == config.n_epochs:

            cvae_test(epoch, test_loader, model, data_products_path, config)

        # early stopping check
        if EARLY_STOPPING and n_epoch_without_improvement >= EARLY_STOPPING_THRESHOLD:
            print("\033[96m\033[1m\nStopping Early\033[0m\n")
            stopped_early = True
            epochs_trained = epoch
            break

    print("\033[96m\033[1m\nTraining complete\033[0m\n")

    # -----------------------------------------------------------------
    # Save best model and loss functions
    # -----------------------------------------------------------------
    utils_save_model(best_model.state_dict(), data_products_path, config.profile_type, best_epoch, best_model=True)

    utils_save_loss(train_loss_array, data_products_path, config.profile_type, config.n_epochs, prefix='train')
    utils_save_loss(val_loss_array, data_products_path, config.profile_type, config.n_epochs, prefix='val')

    # -----------------------------------------------------------------
    # Evaluate best model by using test set
    # -----------------------------------------------------------------
    cvae_test(best_epoch, test_loader, best_model, data_products_path, config, best_model=True)

    # -----------------------------------------------------------------
    # Save additional information to config object for later use
    # -----------------------------------------------------------------
    setattr(config, 'best_epoch', best_epoch)

    setattr(config, 'stopped_early', stopped_early)
    setattr(config, 'epochs_trained', epochs_trained)

    # -----------------------------------------------------------------
    # Overwrite config object
    # -----------------------------------------------------------------
    utils_save_config_to_log(config)
    utils_save_config_to_file(config)

    # -----------------------------------------------------------------
    # Fin
    # -----------------------------------------------------------------
    print('All done!')

    # -----------------------------------------------------------------
    # Optional: analysis
    # -----------------------------------------------------------------
    if config.analysis:
        print("\n\033[96m\033[1m\nRunning analysis\033[0m\n")

        analysis_loss_plot(config)
        analysis_auto_plot_profiles(config, k=5, prefix='best')
        analysis_parameter_space_plot(config, prefix='best')


# -----------------------------------------------------------------
#  The following is executed when the script is run
# -----------------------------------------------------------------
if __name__ == "__main__":

    # parse arguments
    parser = argparse.ArgumentParser(description='ML-RT - Cosmological radiative transfer with neural networks (CVAE)')

    # arguments for data handling
    parser.add_argument('--data_dir', type=str, metavar='(string)', help='Path to data directory', required=True)

    parser.add_argument('--out_dir', type=str, default='output', metavar='(string)',
                        help='Path to output directory, used for all plots and data products, default: ./output/')

    parser.add_argument("--testing_interval", type=int, default=100, help="epoch interval between testing runs")

    # physics related arguments
    parser.add_argument('--profile_type', type=str, default='H', metavar='(string)',
                        help='Select H for neutral hydrogen fraction or T for temperature profiles (default: H)')
    parser.add_argument("--profile_len", type=int, default=1500, help="number of profile grid points")
    parser.add_argument("--n_parameters", type=int, default=8, help="number of RT parameters (5 or 8)")

    # network model switch
    parser.add_argument('--model', type=str, default='CVAE1', metavar='(string)',
                        help='Pick a model: CVAE1 (default) or VAE1')

    # network optimisation
    parser.add_argument("--n_epochs", type=int, default=100, help="number of epochs of training")
    parser.add_argument("--batch_size", type=int, default=32, help="size of the batches (default=32)")

    parser.add_argument("--batch_norm", dest='batch_norm', action='store_true',
                        help="use batch normalisation in network (default)")
    parser.add_argument('--no-batch_norm', dest='batch_norm', action='store_false',
                        help="use batch normalisation in network")
    parser.set_defaults(batch_norm=True)

    parser.add_argument("--dropout", dest='dropout', action='store_true',
                        help="use dropout regularisation in network (default)")
    parser.add_argument("--no-dropout", dest='dropout', action='store_false',
                        help="do not use dropout regularisation in network")
    parser.set_defaults(dropout=True)

    parser.add_argument("--dropout_value", type=float, default=0.25, help="dropout probability, default=0.25 ")

    parser.add_argument("--latent_dim", type=int, default=20, help="dimensionality of the latent space")

    parser.add_argument("--lr", type=float, default=0.0001, help="adam: learning rate, default=0.0002 ")

    parser.add_argument("--b1", type=float, default=0.9,
                        help="adam: beta1 - decay of first order momentum of gradient, default=0.9")
    parser.add_argument("--b2", type=float, default=0.999,
                        help="adam: beta2 - decay of first order momentum of gradient, default=0.999")

    # use blow out filter?
    parser.add_argument("--filter_blowouts", dest='analysis', action='store_true',
                        help="use blowout filter on data set (default)")
    parser.add_argument("--no-filter_blowouts", dest='analysis', action='store_false',
                        help="do not use blowout filter on data set")
    parser.set_defaults(filter_blowouts=True)

    # cut parameter space
    parser.add_argument("--filter_parameters", dest='analysis', action='store_true',
                        help="use user_config to filter data set by parameters")
    parser.add_argument("--no-filter_parameters", dest='analysis', action='store_false',
                        help="do not use user_config to filter data set by parameters (default)")
    parser.set_defaults(filter_parameters=False)

    # analysis
    parser.add_argument("--analysis", dest='analysis', action='store_true',
                        help="automatically generate some plots (default)")
    parser.add_argument("--no-analysis", dest='analysis', action='store_false', help="do not run analysis")
    parser.set_defaults(analysis=True)

    my_config = parser.parse_args()

    # sanity checks
    if my_config.data_dir is None:
        print('\nError: Parameter data_dir must not be empty. Exiting.\n')
        argparse.ArgumentParser().print_help()
        exit(1)

    if my_config.n_parameters not in [5, 8]:
        print('\nError: Number of parameters can currently only be either 5 or 8. Exiting.\n')
        argparse.ArgumentParser().print_help()
        exit(1)

    if my_config.n_parameters == 5:
        parameter_limits = ps.p5_limits
        parameter_names_latex = ps.p5_names_latex

    if my_config.n_parameters == 8:
        parameter_limits = ps.p8_limits
        parameter_names_latex = ps.p8_names_latex

    if my_config.model not in ['CVAE1', 'VAE1']:
        my_config.model = 'CVAE1'

    # print summary
    print("\nUsed parameters:\n")
    for arg in vars(my_config):
        print("\t", arg, getattr(my_config, arg))

    my_config.out_dir = os.path.abspath(my_config.out_dir)
    my_config.data_dir = os.path.abspath(my_config.data_dir)

    # run main program
    main(my_config)
