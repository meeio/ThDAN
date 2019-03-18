import itertools

import numpy as np
import torch

from mdata.partial_folder import MultiFolderDataHandler
from mground.gpu_utils import current_gpu_usage
from mground.math_utils import entropy, make_weighted_sum
from mtrain.mloger import GLOBAL, LogCapsule

from ..basic_module import DAModule
from .networks.networks import DomainClassifier
from ..utils.gradient_reverse import GradReverseLayer
from .params import get_params

param = get_params()


def get_lambda(iter_num, max_iter, high=1.0, low=0.0, alpha=10.0):
    return np.float(
        2.0 * (high - low) / (1.0 + np.exp(-alpha * iter_num / max_iter))
        - (high - low)
        + low
    )


def get_lr_scaler(
    iter_num, max_iter, init_lr=param.lr, alpha=10, power=0.75
):
    lr_scaler = np.float((1 + alpha * (iter_num / max_iter)) ** (-power))
    return lr_scaler


class DANN(DAModule):
    def __init__(self):
        super(DANN, self).__init__(param)
        self._all_ready()

    def _regist_networks(self):

        if True:
            from .networks.resnet50 import ResFc, ResClassifer
            F = ResFc()
            C = ResClassifer(class_num=31)
        else:
            from .networks.alex import AlexNetFc, AlexClassifer
            F = AlexNetFc()
            C = AlexClassifer(class_num=31)

        grad_reverse = GradReverseLayer(
            coeff=lambda: get_lambda(self.current_step, self.total_steps)
        )
        D = DomainClassifier(input_dim=2048, reversed_function=grad_reverse)

        return {"F": F, "C": C, "D": D}

    def _regist_losses(self):

        optimer = {
            "type": torch.optim.SGD,
            "lr": self.params.lr,
            "momentum": 0.95,
            "weight_decay": 0.001,
            "nesterov": True,
            "lr_mult": {"F": 0.1},
        }

        lr_scheduler = {
            "type": torch.optim.lr_scheduler.LambdaLR,
            "lr_lambda": lambda steps: get_lr_scaler(
                steps, self.total_steps
            ),
            "last_epoch": 0,
        }

        self.define_loss(
            "global_looss",
            networks=["F", "C", "D"],
            optimer=optimer,
            decay_op=lr_scheduler,
        )

        self.define_log("classify", "discrim")

    def _train_step(self, s_img, s_label, t_img):

        imgs = torch.cat([s_img, t_img], dim=0)
        domain = torch.cat([self.SOURCE, self.TARGET], dim=0)

        backbone_feature = self.F(imgs)
        feature, pred_class = self.C(backbone_feature)
        pred_domain = self.D(feature)

        s_pred_class, _ = torch.chunk(pred_class, chunks=2, dim=0)
        loss_classify = self.ce(s_pred_class, s_label)

        loss_dis = self.bce(pred_domain, domain)

        self._update_logs({"classify": loss_classify, "discrim": loss_dis})
        self._update_loss("global_looss", loss_classify + loss_dis)

        del loss_classify, loss_dis

    def _valid_step(self, img):
        feature = self.F(img)
        _, prediction = self.C(feature)
        return prediction