from collections import namedtuple
import torch
from Models import *
import numpy as np
import datetime
import pandas as pd
import xlsxwriter

model_params = namedtuple(
    'model_params',
    'name, epochs, valid_epochs max_pooling_rate, learning_rate',
)

class ship_training_app:
    
    def __init__(self, train_dl, valid_dl, model_params):
        """
        init training with given params
        
        Args:
            * train_dl, train data set dataloader
            * valid_dl, validation data set dataloader
            * model_params, name+model params. Names: "CNN_REG"
        """
        
        self.train_dl = train_dl
        self.valid_dl = valid_dl
        self.model_params = model_params

        self.use_cuda = torch.cuda.is_available()        
        self.device = torch.device("cuda" if self.use_cuda and self.model_params.gpu else "cpu")
        
        
        self.model = self.init_models()
        self.optimizer = self.init_optimizer()
        
        self.mse_loss = torch.nn.MSELoss(reduction = 'none')
        self.mae_loss = torch.nn.L1Loss(reduction = 'none')

        # Results
                # Set savers
        self.training_results_dict = {
            'epoch': [],
            'mse_general': [],
            'mae_general': [],
            'mse_Hs': [],
            'mse_Tz': [],
            'mse_Dp': [],
            'mae_Hs': [],
            'mae_Tz': [],
            'mae_Dp': [],
        }

        self.validation_results_dict = {
            'epoch': [],
            'mse_general': [],
            'mae_general': [],
            'mse_Hs': [],
            'mse_Tz': [],
            'mse_Dp': [],
            'mae_Hs': [],
            'mae_Tz': [],
            'mae_Dp': [],
        }
        
    def init_models(self):

        assert self.model_params.name in ["CNN_REG"], f"Wrong model name, got: {self.model_params.name}"

        print(f"USING MODEL: {self.model_params.name}")

        if self.model_params.name == "CNN_REG":
            _model = CNN_REG(max_pooling_ratio = self.model_params.max_pooling_rate, 
            scaler = self.model_params.scaler)
        
        if self.model_params.gpu:
            print(f"USING GPU: {self.device}")
            _model = _model.to(self.device)
        return _model
    
    def init_optimizer(self):
        """
            Init optimizer: Feel free to add other optmizers. UPGRADE: optimizer as param
            self.lr = 0.06 0.03
        """
        print(f"USING OPTIMIZER: {self.model_params.opt_name} / LR:{self.model_params.learning_rate}")
    
        assert self.model_params.opt_name in ["SGD", "ADAM"], f"Wrong optimizer name, got: {self.model_params.opt_name}"

        if self.model_params.opt_name == 'SGD':
            return torch.optim.SGD(self.model.parameters(), lr=self.model_params.learning_rate, 
            momentum=0.9)

        if self.model_params.opt_name == 'ADAM':
            return torch.optim.Adam(self.model.parameters(), lr = self.model_params.learning_rate)
    
    def train_model(self, data):
        """
        Training model function. 

        Args:
            * data, dataloader of the train dataset
        """

        # Metrics
        # Loss MSE MAE _metrics[0] = MSE _metric[1] = MAE
        _metrics = torch.zeros(8, len(data.dataset), device = self.device)
        
        # Swap to mode train
        self.model.train()

        # Shuffle dataset and create enum object
        data.dataset.shuffle_samples()
        _batch_iter = enumerate(data)
        
        # Go trough batches
        for _index, _batch in _batch_iter:
            # Clear grads
            self.optimizer.zero_grad()
            
            # Calc loss
            _loss = self.get_loss(_index, _batch, _metrics)
            
            # Propagate loss
            _loss.backward()
            
            # Apply loss
            self.optimizer.step()
        
        # Return metrics
        return _metrics

    def validate_model(self, data):
        """
        Validation model function

        Args:
            * data, dataloader of the train dataset
        """

        # Metrics
        # Loss MSE MAE _metrics[0] = MSE _metric[1] = MAE
        _metrics = torch.zeros(8, len(data.dataset), device = self.device)

        # We don't need calculate gradients 
        with torch.no_grad():
            # Set model in evaluate mode - no batchnorm and dropout
            self.model.eval()

            # Go trough data
            for _index, _batch in enumerate(data):
                # Get loss
                _loss = self.get_loss(_index, _batch, _metrics)
        
        # Return metrics        
        return _metrics

    def get_loss(self, index, batch, metrics):
        """
        Function that calculates loss. Loss in this code is MeanSquaredError

        Args:
            * index, int, batch index needed to populate _metrics

            * batch, tensor, data

            * metrics, tensor, container to save data
        """

        # Parse _batch
        _input_data, _output_data, _info_data = batch
        
        # Augmenet data
        #if aug:
        #    _input_data, _mask_data = self.aug_model(_input_data, _mask_data)
        
        # Transfer data to GPU
        _input_data = _input_data.to(self.device, non_blocking = True)
        _output_data = _output_data.to(self.device, non_blocking = True)
        
        
        # Loss
        # Caluclate loss

        _prediction = self.model(_input_data)
        _mse_loss = self.mse_loss(_prediction, _output_data)
        _mae_loss = self.mae_loss(_prediction, _output_data)
        
        # For metrics
        _begin_index = self.train_dl.batch_size * index
        _end_index = _begin_index + _input_data.size(0)
        
        # Calculate metrics
        with torch.no_grad():
            metrics[0, _begin_index:_end_index] = _mse_loss.mean()
            metrics[1, _begin_index:_end_index] = _mae_loss.mean()
            metrics[2, _begin_index:_end_index] = _mse_loss[:,0]
            metrics[3, _begin_index:_end_index] = _mse_loss[:,1]
            metrics[4, _begin_index:_end_index] = _mse_loss[:,2]
            metrics[5, _begin_index:_end_index] = _mae_loss[:,0]
            metrics[6, _begin_index:_end_index] = _mae_loss[:,1]
            metrics[7, _begin_index:_end_index] = _mae_loss[:,2]
        # Return mean of all loss          
        return _mse_loss.mean()
    
    def eval_metrics(self, epoch, metrics, mode):
        """
            Function for metric evaluation
        """
        # Transfer to cpu
        _metrics = metrics.to('cpu')
        _metrics = _metrics.detach().numpy()
        
        # Calculate means
        _mse = _metrics[0]
        _mae = _metrics[1]

        # Print info
        print("{}: {} : MSE:{:.5f}, MAE:{:.5f}".format(mode, epoch, np.mean(_mse), np.mean(_mae)))
        return _mse
     
    def save_model(self, epoch, best):
        """
            Function for model saving

            Args:
                * epoch, int, epoch being saved

                * best, boolean, Is this the best model
        """

        _model = self.model
        
        # For paralel
        if isinstance(_model, torch.nn.DataParallel):
            _model = _model.module
        
        # Define saving state
        _state = {
            'time': str(datetime.datetime.now()),
            'model_state': _model.state_dict(),
            'model_name': type(_model).__name__,
            'optimizer_state': self.optimizer.state_dict(),
            'optimizer_name': type(self.optimizer).__name__,
            'epoch': epoch
        }
        
        # Save last model
        torch.save(_state, 'last_model-true.pth')
        print('Saving model!')
        
        # Save best model
        if best:
            print('Saving best model!')
            torch.save(_state, 'best_model-true.pth')

    def save_metrics(self, epoch, metrics, mode):
        """
        function to populate metrics dict
        """
        # Transfer metrics to CPU
        _metrics = metrics.to('cpu')
        _metrics = _metrics.detach().numpy()

        if mode == 'Train':
            self.training_results_dict['epoch'].append(epoch)
            self.training_results_dict['mse_general'].append(np.mean(_metrics[0]))
            self.training_results_dict['mae_general'].append(np.mean(_metrics[1]))
            self.training_results_dict['mse_Hs'].append(np.mean(_metrics[2]))
            self.training_results_dict['mse_Tz'].append(np.mean(_metrics[3]))
            self.training_results_dict['mse_Dp'].append(np.mean(_metrics[4]))
            self.training_results_dict['mae_Hs'].append(np.mean(_metrics[5]))
            self.training_results_dict['mae_Tz'].append(np.mean(_metrics[6]))
            self.training_results_dict['mae_Dp'].append(np.mean(_metrics[7]))
        
        if mode == 'Valid':
            self.validation_results_dict['epoch'].append(epoch)
            self.validation_results_dict['mse_general'].append(np.mean(_metrics[0]))
            self.validation_results_dict['mae_general'].append(np.mean(_metrics[1]))
            self.validation_results_dict['mse_Hs'].append(np.mean(_metrics[2]))
            self.validation_results_dict['mse_Tz'].append(np.mean(_metrics[3]))
            self.validation_results_dict['mse_Dp'].append(np.mean(_metrics[4]))
            self.validation_results_dict['mae_Hs'].append(np.mean(_metrics[5]))
            self.validation_results_dict['mae_Tz'].append(np.mean(_metrics[6]))
            self.validation_results_dict['mae_Dp'].append(np.mean(_metrics[7]))

    def export_metrics_to_xlsx(self, best_epoch, best_score):
        """
        Function that exports model's training and validation metrics to dictionary
        """
        
        # Generate writer for a given model
        if self.model_params.name == 'CNN_REG':
            _writer = pd.ExcelWriter(f"{self.model_params.name}:{self.model_params.max_pooling_rate}:{self.model_params.scaler}_{self.model_params.opt_name}" +  
                f":{self.model_params.learning_rate}_{best_epoch}_mse:{best_score:5f}.xlsx", engine = 'xlsxwriter')
        
        # Generate dataframes
        _df_train = pd.DataFrame.from_dict(self.training_results_dict)
        _df_valid = pd.DataFrame.from_dict(self.validation_results_dict)

        _df_train.to_excel(_writer, sheet_name="Training", index = False)
        _df_valid.to_excel(_writer, sheet_name="Validation", index = False)
        _writer.save() 

    def load_model(self, path):
        """
            Function that loads model.

            Args:
                * path, string, path to the model checkpoint
        """
        print("LOADING MODEL")
        
        _state_dict = torch.load(path)
        self.model.load_state_dict(_state_dict['model_state'])
        self.optimizer.load_state_dict(_state_dict['optimizer_state'])
        self.optimizer.name = _state_dict['optimizer_name']
        self.model.name = _state_dict['optimizer_name']
        
        print(f"LOADING MODEL, epoch {_state_dict['epoch']}"
                 + f", time {_state_dict['time']}")
    
    def main(self):
        """
            Main train function.
        """
        print(f"Starting training {self}")
            
        # Set score 
        _best_score = 1000.0
        _best_epoch = 0
        for _epoch in range(1, self.model_params.epochs +1):
            print(f"Epoch {_epoch} / {self.model_params.epochs}")
            
            # Trening
            _metrics = self.train_model(self.train_dl)
            self.eval_metrics(_epoch, _metrics, 'Train')
            self.save_model(_epoch, best = False)
            self.save_metrics(_epoch, _metrics, 'Train')

            
            # Validation
            if _epoch == 1 or _epoch % self.model_params.valid_epochs == 0:
                _metrics = self.validate_model(self.valid_dl)
                print("*************")
                _mse = self.eval_metrics(_epoch, _metrics, 'Valid')
                print("*************")
                self.save_metrics(_epoch, _metrics, 'Valid')
                _mse = np.mean(_mse)

                if _epoch == 1 or ( _mse < _best_score):
                    self.save_model(_epoch, best = True)
                    _best_score = _mse
                    _best_epoch = _epoch
            
            # Early stopping
            if _epoch - _best_epoch  > self.model_params.valid_epochs * 7:
                print(f"Early stopping at epoch: {_epoch}")
                break
        
        # Save metrics
        self.export_metrics_to_xlsx(_best_epoch, _best_score)

        # Release memory
        torch.cuda.empty_cache()

        