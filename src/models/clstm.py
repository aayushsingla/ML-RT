from torch import nn
import torch


class CLSTM(nn.Module):
    def __init__(self, conf, device):
        super(CLSTM, self).__init__()

        self.input_size = conf.n_parameters
        self.seq_len = conf.profile_len
        self.device = device

        def block(features_in, features_out):
            layers = [nn.Linear(features_in, features_out)]
            layers.append(nn.LeakyReLU(0.2, inplace=True))
            return layers

        # Args: expects input of shape: (batch_size, n_parameters)
        #       output of shape: (batch_size, 2*time_series_length)
        self.linear_model = nn.Sequential(
            *block(self.input_size, 64),
            *block(64, 128),
            *block(128, 256),
            *block(256, 512),
            *block(512, 1024),
            *block(1024, self.seq_len),
            nn.Linear(self.seq_len, self.seq_len * 2)
        )

        # Args: expects input of shape: (batch_size, time_series_length, input_size)
        #       output of shape: (batch_size, time_series_length, 2*hidden_size): x2 because, bidirectional_lstm
        self.lstm = nn.LSTM(input_size=1, hidden_size=4, batch_first=True, bidirectional=True)

        self.lstm_H = nn.LSTM(input_size=8, hidden_size=1, batch_first=True, bidirectional=False)
        self.lstm_T = nn.LSTM(input_size=8, hidden_size=1, batch_first=True, bidirectional=False)
        self.lstm_He1 = nn.LSTM(input_size=8, hidden_size=1, batch_first=True, bidirectional=False)
        self.lstm_He2 = nn.LSTM(input_size=8, hidden_size=1, batch_first=True, bidirectional=False)

        # Args: expects input of shape: (batch_size, 2*2*time_series_length)
        #       output of shape: (batch_size, time_series_length)
        self.out_layer_H = nn.Linear(2 * self.seq_len, self.seq_len)
        self.out_layer_T = nn.Linear(2 * self.seq_len, self.seq_len)
        self.out_layer_He1 = nn.Linear(2 * self.seq_len, self.seq_len)
        self.out_layer_He2 = nn.Linear(2 * self.seq_len, self.seq_len)

    def forward(self, x):

        # initialise hidden states for the lstm
        (hidden_state, cell_state) = self.init_hidden_state(batch_size=x.size()[0], hidden_size=4, bidirectional=True)

        (hidden_state_h, cell_state_h) = self.init_hidden_state(batch_size=x.size()[0], hidden_size=1)
        (hidden_state_t, cell_state_t) = self.init_hidden_state(batch_size=x.size()[0], hidden_size=1)
        (hidden_state_he1, cell_state_he1) = self.init_hidden_state(batch_size=x.size()[0], hidden_size=1)
        (hidden_state_he2, cell_state_he2) = self.init_hidden_state(batch_size=x.size()[0], hidden_size=1)

        x = self.linear_model(x)
        # x.size(): (batch_size, 2*time_series_length) => (batch_size, 2*time_series_length, input_size)
        x = torch.unsqueeze(x, dim=2)
        x, (hidden_state, cell_state) = self.lstm(x, (hidden_state, cell_state))
        # x.size(): (batch_size, 2*time_series_length, 2*input_size) => (batch_size, 2*2*time_series_length)
        # x = x.reshape(x.size()[0], -1)
        # x_h = torch.stack((x[:, :, 0], x[:, :, 4]), dim=2).reshape(x.size()[0], -1)
        # x_t = torch.stack((x[:, :, 1], x[:, :, 5]), dim=2).reshape(x.size()[0], -1)
        # x_he1 = torch.stack((x[:, :, 2], x[:, :, 6]), dim=2).reshape(x.size()[0], -1)
        # x_he2 = torch.stack((x[:, :, 3], x[:, :, 7]), dim=2).reshape(x.size()[0], -1)
        x_h, _ = self.lstm_H(x, (hidden_state_h, cell_state_h))
        x_t, _ = self.lstm_T(x, (hidden_state_t, cell_state_t))
        x_he1, _ = self.lstm_He1(x, (hidden_state_he1, cell_state_he1))
        x_he2, _ = self.lstm_He2(x, (hidden_state_he2, cell_state_he2))

        x_h = x_h.squeeze(dim=2)
        x_t = x_t.squeeze(dim=2)
        x_he1 = x_he1.squeeze(dim=2)
        x_he2 = x_he2.squeeze(dim=2)

        x_h = self.out_layer_H(x_h)
        x_t = self.out_layer_T(x_t)
        x_he1 = self.out_layer_He1(x_he1)
        x_he2 = self.out_layer_He2(x_he2)

        return x_h, x_t, x_he1, x_he2

    def init_hidden_state(self, batch_size, hidden_size, bidirectional=False):
        if bidirectional:
            hidden_state = torch.zeros(2, batch_size, hidden_size, device=self.device)
            cell_state = torch.zeros(2, batch_size, hidden_size, device=self.device)
        else:
            hidden_state = torch.zeros(1, batch_size, hidden_size, device=self.device)
            cell_state = torch.zeros(1, batch_size, hidden_size, device=self.device)

        # Weights initialization
        torch.nn.init.xavier_normal_(hidden_state)
        torch.nn.init.xavier_normal_(cell_state)

        return (hidden_state, cell_state)

# class CLSTM2(nn.Module):
#     def __init__(self, conf, device):
#         super(CLSTM2, self).__init__()

#         self.input_size = conf.n_parameters
#         self.seq_len = conf.profile_len
#         self.device = device
#         self.num_layers = 1

#         def block(features_in, features_out):
#             layers = [nn.Linear(features_in, features_out)]
#             layers.append(nn.LeakyReLU(0.2, inplace=True))
#             return layers

#         # Args: expects input of shape: (batch_size, n_parameters)
#         #       output of shape: (batch_size, 2*time_series_length)
#         self.linear_model = nn.Sequential(
#             *block(self.input_size, 64),
#             *block(64, 128),
#             *block(128, 256),
#             *block(256, 512),
#             *block(512, 1024),
#             *block(1024, self.seq_len),
#             nn.Linear(self.seq_len, self.seq_len * 2)
#         )

#         # Args: expects input of shape: (batch_size, time_series_length, input_size)
#         #       output of shape: (batch_size, time_series_length, 2*hidden_size): x2 because, bidirectional_lstm
#         self.lstm_cell_H = nn.LSTMCell(input_size=1, hidden_size=1, batch_first=True)
#         self.lstm_cell_T = nn.LSTMCell(input_size=1, hidden_size=1, batch_first=True)
#         self.lstm_cell_He1 = nn.LSTMCell(input_size=1, hidden_size=1, batch_first=True)
#         self.lstm_cell_He2 = nn.LSTMCell(input_size=1, hidden_size=1, batch_first=True)

#         # Args: expects input of shape: (batch_size, 2*2*time_series_length)
#         #       output of shape: (batch_size, time_series_length)
#         self.out_layer_H = nn.Linear(2 * 2 * self.seq_len, self.seq_len)
#         self.out_layer_T = nn.Linear(2 * 2 * self.seq_len, self.seq_len)
#         self.out_layer_He1 = nn.Linear(2 * 2 * self.seq_len, self.seq_len)
#         self.out_layer_He2 = nn.Linear(2 * 2 * self.seq_len, self.seq_len)

#     def forward(self, x):

#         # initialise hidden states for the lstm
#         (hidden_state, cell_state) = self.init_hidden_state(batch_size=x.size()[0])

#         out_lstm = torch.empty((self.batch_size, 0))
#         x = self.linear_model(x)
#         # x.size(): (batch_size, 2*time_series_length) => (batch_size, 2*time_series_length, input_size)
#         x = torch.unsqueeze(x, dim=2)
#         x, (hidden_state, cell_state) = self.lstm(x, (hidden_state, cell_state))
#         # x.size(): (batch_size, 2*time_series_length, 2*input_size) => (batch_size, 2*2*time_series_length)
#         # x = x.reshape(x.size()[0], -1)
#         x_h = x[:, :, 0:2].reshape(x.size()[0], -1)
#         x_t = x[:, :, 2:4].reshape(x.size()[0], -1)
#         x_he1 = x[:, :, 4:6].reshape(x.size()[0], -1)
#         x_he2 = x[:, :, 6:8].reshape(x.size()[0], -1)

#         x_h = self.out_layer_H(x_h)
#         x_t = self.out_layer_T(x_t)
#         x_he1 = self.out_layer_He1(x_he1)
#         x_he2 = self.out_layer_He2(x_he2)

#         return x_h, x_t, x_he1, x_he2

#     def init_hidden_state(self, batch_size):
#         # x2 because, bidirectional lstm
#         hidden_state = torch.zeros(2 * self.num_layers, batch_size, 8, device=self.device)
#         cell_state = torch.zeros(2 * self.num_layers, batch_size, 8, device=self.device)

#         # Weights initialization
#         torch.nn.init.xavier_normal_(hidden_state)
#         torch.nn.init.xavier_normal_(cell_state)

#         return (hidden_state, cell_state)

