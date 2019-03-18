import torch

from mmodel import get_module

if __name__ == "__main__":

    # torch.backends.cudnn.benchmark = True
    torch.cuda.empty_cache()
    _, A = get_module("DANN")
    A.train_module()
