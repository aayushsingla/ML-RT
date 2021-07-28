import numpy as np


# -----------------------------------------------------------------
# Cuts in the parameter space
# -----------------------------------------------------------------
def filter_cut_parameter_space(H_profiles, T_profiles, global_parameters):
    """
     This function makes cuts to the parameter space according to some user-specified limits.
     The limits could be provided as an argument (2D numpy array) in the same format as the ones
     in parameter_settings.py. They could be either come from a user_settings.py or we could use the hard
     coded parameter section in the script files (e.g. mlp.py). I thing the latter might be a bit cleaner.


     Args:
         numpy objects containing the hydrogen, temperature profiles, and parameters

     """

    print("\nParameter space filter: Deleting a total of __ samples. __ remaining.")


# -----------------------------------------------------------------
# Blow out filter
# -----------------------------------------------------------------
def filter_blowout_profiles(H_profiles, T_profiles, global_parameters, threshold=0.9):
    """
    This function filters out all blow-out profiles, i.e. removes all hydrogen ionisation profiles
    whose ionisation front is beyond the edge of the computing grid. The same action is
    performed for their corresponding temperature counterparts.

    Args:
        numpy objects containing the hydrogen, temperature profiles, and parameters
        threshold : Filter threshold [0,1], should be close to 1.
    """

    # identify all blow-outs
    # blow out is a x_{H_{II}} profile for which all array values are above a certain threshold (e.g. < 0.9)

    # 0) for each profile find the min value
    profile_minima = np.min(H_profiles, axis=1)

    # 1) find all profiles for which the min > threshold
    deletion_indices = np.where(profile_minima > threshold)[0]

    for i in range(0, len(deletion_indices)):
        index = deletion_indices[i]

        #print("Deletions for index %d [%d]:"%(i, index))
        #print("Parameters:", global_parameters[index,:])
        #print("Hprofile:", H_profiles[index,:])
        #print("--------------------------------------------------------------------------------------")

    H_profiles = np.delete(H_profiles, deletion_indices, axis=0)
    T_profiles = np.delete(T_profiles, deletion_indices, axis=0)
    global_parameters = np.delete(global_parameters, deletion_indices, axis=0)

    print("\nBlow-out filter: Deleting a total of %d samples. %d remaining."%(len(deletion_indices), len(H_profiles)))

    return H_profiles, T_profiles, global_parameters

