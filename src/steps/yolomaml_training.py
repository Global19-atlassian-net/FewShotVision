import os

from pipeline.steps import AbstractStep
import torch

from src.loaders.data_managers import DetectionSetDataManager
from src.methods import YOLOMAML
from src.utils import configs
from src.utils.io_utils import set_and_print_random_seed
from src.yolov3.model import Darknet
from src.yolov3.utils.parse_config import parse_data_config


class YOLOMAMLTraining(AbstractStep):
    '''
    This step handles the training of the algorithm on the base dataset
    '''

    def __init__(
            self,
            dataset='yolov3/config/black.data',
            model_config='yolov3/config/yolov3.cfg',
            n_way=5,
            n_shot=5,
            n_query=16,
            optimizer='Adam',
            learning_rate=0.001,
            n_epoch=100,
            n_episode=100,
            random_seed=None,
            output_dir=configs.save_dir,
    ):
        '''
        Args:
            dataset (str): path to data config file
            model_config (str): path to model definition file
            n_way (int): number of labels in a detection task
            n_shot (int): number of support data in each class in an episode
            n_query (int): number of query data in each class in an episode
            optimizer (str): must be a valid class of torch.optim (Adam, SGD, ...)
            learning_rate (float): learning rate fed to the optimizer
            n_epoch (int): number of meta-training epochs
            n_episode (int): number of episodes per epoch during meta-training
            random_seed (int): seed for random instantiations ; if none is provided, a seed is randomly defined
            output_dir (str): path to experiments output directory
        '''

        self.dataset = dataset
        self.model_config = model_config
        self.n_way = n_way
        self.n_shot = n_shot
        self.n_query = n_query
        self.optimizer = optimizer
        self.learning_rate = learning_rate
        self.n_epoch = n_epoch
        self.n_episode = n_episode
        self.random_seed = random_seed
        self.checkpoint_dir = output_dir

        self.device = torch.device("cuda" if torch.cuda.is_available() else "cpu")

    def apply(self):
        '''
        Execute the YOLOMAMLTraining step
        Returns:
            dict: a dictionary containing the whole state of the model that gave the higher validation accuracy

        '''
        set_and_print_random_seed(self.random_seed, True, self.checkpoint_dir)

        data_config = parse_data_config(self.dataset)
        train_path = data_config["train"]
        valid_path = data_config["valid"]

        base_loader = self._get_data_loader(train_path)
        val_loader = self._get_data_loader(valid_path)

        model = self._get_model()

        return self._train(base_loader, val_loader, model)

    def dump_output(self, _, output_folder, output_name, **__):
        pass

    def _train(self, base_loader, val_loader, model):
        '''
        Trains the model on the base set
        Args:
            base_loader (torch.utils.data.DataLoader): data loader for base set
            val_loader (torch.utils.data.DataLoader): data loader for validation set
            model (YOLOMAML): neural network model to train

        Returns:
            dict: a dictionary containing the whole state of the model that gave the higher validation accuracy

        '''
        optimizer = self._get_optimizer(model)

        for epoch in range(self.n_epoch):
            model.train()
            model.train_loop(epoch, base_loader, optimizer)

            #TODO : add validation

            if epoch == self.n_epoch - 1:
                outfile = os.path.join(self.checkpoint_dir, '{:d}.tar'.format(epoch))
                torch.save({'epoch': epoch, 'state': model.state_dict()}, outfile)

        return {'epoch': self.n_epoch, 'state': model.state_dict()}

    def _get_optimizer(self, model):
        """
        Get the optimizer from string self.optimizer
        Args:
            model (torch.nn.Module): the model to be trained

        Returns: a torch.optim.Optimizer object parameterized with model parameters

        """
        assert hasattr(torch.optim, self.optimizer), "The optimization method is not a torch.optim object"
        optimizer = getattr(torch.optim, self.optimizer)(model.parameters(), lr=self.learning_rate)

        return optimizer

    def _get_data_loader(self, path_to_data_file):
        '''

        Args:
            path_to_data_file (str): path to file containing paths to images

        Returns:
            torch.utils.data.DataLoader: samples data in the shape of a detection task
        '''
        data_manager = DetectionSetDataManager(self.n_way, self.n_shot, self.n_query, self.n_episode)

        return data_manager.get_data_loader(path_to_data_file)

    def _get_model(self):
        '''

        Returns:
            YOLOMAML: meta-model
        '''

        base_model = Darknet(self.model_config)

        model = YOLOMAML(
            base_model,
            self.n_way,
            self.n_shot,
            self.n_query,
            approx=False,
            n_task=4,
            task_update_num=5,
            train_lr=self.learning_rate,
            device=self.device
        )

        return model