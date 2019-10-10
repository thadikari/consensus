# -*- coding: future_fstrings -*-

import tensorflow as tf
import numpy as np
import argparse
import json
import os

from mnist import get_data
from graphs import doubly_stoch_from_nc_pairs


class Evaluator:
    def __init__(self):
        self.w_len = 784*10+10
        pl = lambda sh_: tf.compat.v1.placeholder(tf.float32, shape=sh_)
        self.pl_w = pl(self.w_len)
        self.pl_x = pl((None, 784))
        self.pl_y = pl((None, 10))
        self.loss = self.func(self.pl_w, self.pl_x, self.pl_y)
        self.grad = tf.gradients(self.loss, self.pl_w)[0]
        self.sess = tf.compat.v1.Session()

    def func(self, w_, x_, y_):
        reshape = tf.compat.v1.reshape
        w, b = reshape(w_[:784*10], (784,10)), w_[784*10:]
        #print(w.get_shape(), b.get_shape())
        logits = x_@w+b
        sm = tf.nn.softmax_cross_entropy_with_logits_v2
        #return tf.reduce_mean(tf.square(logits - y_))
        # return tf.reduce_mean(tf.reduce_sum(sm(y_, logits), axis=1))
        return tf.reduce_mean(sm(y_, logits))

    def get_size(self):
        return self.w_len

    def eval(self, w_, x_, y_):
        dd = {self.pl_w:w_, self.pl_x:x_, self.pl_y:y_}
        loss, grad = self.sess.run([self.loss, self.grad], feed_dict=dd)
        return loss, grad


class Worker:
    def __init__(self, eval, xy_local, xy_global):
        self.eval = eval
        self.tot = len(xy_local[0])
        self.xy_local = xy_local
        self.xy_global = xy_global

    def get_local_loss(self, weights):
        return self.eval.eval(weights, *self.xy_local)[0]

    def get_global_loss(self, weights):
        return float(self.eval.eval(weights, *self.xy_global)[0])

    def get_num_samples(self):
        if _a.strag_dist=='bern':
            num_samples = _a.num_samples if np.random.rand() < _a.strag_dist_param else 1
        elif _a.strag_dist=='gauss':
            num_samples = int(np.random.normal(loc=_a.num_samples, scale=_a.strag_dist_param))
            num_samples = max(1, min(self.tot, num_samples))
        return num_samples

    def prep_data(self, num_samples):
        self.num_samples = num_samples if num_samples>0 else self.get_num_samples()
        self.inds = np.random.choice(self.tot, size=self.num_samples)

    def get_grad(self, weights):
        x_, y_ = [z_[self.inds] for z_ in self.xy_local]
        loss, grad = self.eval.eval(weights, x_, y_)
        return loss, grad, self.num_samples


def grad_combine_equal(grads, num_samples):
    return grads #*len(grads)/len(grads)

def grad_combine_conf(grads, num_samples):
    confs = num_samples/sum(num_samples)
    # print(num_samples)
    return confs[:, np.newaxis]*grads*len(grads)


class Scheme():
    def __init__(self, workers, w_init, mat_P, grad_combine):
        self.workers = workers
        self.comb = grad_combine
        self.mat_P = mat_P

        numw = len(workers)
        self.curr_w = np.zeros([numw, len(w_init)])
        for i in range(numw): self.curr_w[i] = w_init
        self.curr_g = np.zeros([numw, len(w_init)])
        self.curr_numsam = np.zeros(numw)

        self.history = []
        self.eval_global_losses()

    def eval_global_losses(self):
        losses = [wkr.get_global_loss(wgt) for wkr, wgt in zip(self.workers, self.curr_w)]
        # print(np.isclose(self.curr_w, self.curr_w[0]).all())
        self.history.append(losses)
        return sum(losses)/len(losses)

    def step(self):
        step = 0.1
        for i in range(len(self.workers)):
            worker_out = self.workers[i].get_grad(self.curr_w[i])
            _, self.curr_g[i], self.curr_numsam[i] = worker_out
        self.curr_w -= step*self.mat_P@self.comb(self.curr_g, self.curr_numsam)


def main():
    run_id = f'run_{_a.consensus}_{_a.strag_dist}_{_a.strag_dist_param:g}_{_a.num_samples}_{_a.identical_data}_{_a.num_consensus_rounds}_{_a.doubly_stoch}'
    print('run_id:', run_id)

    eval = Evaluator()
    xy_local_gen, xy_global = get_data(_a.identical_data)
    workers = [Worker(eval, xy_, xy_global) for xy_ in xy_local_gen]
    numw = len(workers)

    if _a.consensus=='perfect':
        # simple averaging matrix
        mat_P = np.ones([numw, numw])/numw
    elif _a.consensus=='rand_walk':
        # double stochastic matrix
        W_ = doubly_stoch_from_nc_pairs(_a.adja_mat_nc, numw, _a.doubly_stoch)
        mat_P = np.linalg.matrix_power(W_, _a.num_consensus_rounds)

    w_init = np.random.RandomState(seed=_a.weights_seed).normal(size=eval.get_size())
    sc = lambda comb: Scheme(workers, w_init, mat_P, comb)
    schemes = {'Equal':sc(grad_combine_equal), 'Weighted':sc(grad_combine_conf)}

    for t in range(_a.num_iters):
        ## set number of samples each worker is processing
        for i in range(numw):
            if _a.strag_dist=='round':
                numsam = _a.num_samples if t%numw==i else 1
            elif _a.strag_dist=='equal':
                numsam = _a.num_samples
            else:
                numsam = -1
            workers[i].prep_data(numsam)

        for scheme in schemes: schemes[scheme].step()
        if t%_a.loss_eval_freq==0:
            print('(%d):'%t, {scheme:schemes[scheme].eval_global_losses()
                                             for scheme in schemes})

        if t%_a.save_freq==0 and _a.save:
            with open(os.path.join(_a.data_dir, '%s.json'%run_id), 'w') as fp_:
                dd = vars(_a)
                dd['numw'] = numw
                dd['data'] = {scheme:schemes[scheme].history for scheme in schemes}
                json.dump(dd, fp_, indent=4)

    if _a.plot: plot(schemes)


def plot(schemes):
    import matplotlib.pyplot as plt
    ax = plt.gca()
    for scheme in schemes: ax.plot(schemes[scheme].history, label=scheme)
    ax.legend(loc='best')
    ax.set_xlabel('Iteration')
    ax.set_ylabel('Loss')
    plt.show()


def parse_args():
    parser = argparse.ArgumentParser()

    parser.add_argument('consensus', choices=['perfect', 'rand_walk'])

    parser.add_argument('strag_dist', help='randomness in worker num_samples',  choices=['equal', 'round', 'gauss', 'bern'])
    parser.add_argument('--strag_dist_param', help='sigma or true prob in gauss/bern', type=float, default=1.)
    parser.add_argument('--num_samples', help='num_samples in each sampling method', type=int, default=64)

    parser.add_argument('--identical_data', help='identical sampling across workers', action='store_true')
    parser.add_argument('--weights_seed', help='seed for generating init weights', type=int)

    def_adja_mat = ((0,1), (0,3), (0,5), (0,9), (1,4), (1,5), (1,8),
                    (2,4), (2,7), (2,6), (3,5), (3,6), (3,7),
                    (4,6), (4,7), (4,9), (5,8), (6,7), (6,9), (7,8), (8,9))

    parser.add_argument('--num_consensus_rounds', help='num_consensus_rounds', type=int, default=5)
    parser.add_argument('--adja_mat_nc', help='not-connected pairs in adjacency matrix', default=def_adja_mat)
    parser.add_argument('--doubly_stoch', help='method for generating doubly stochastic matrix', default='metro', choices=['metro', 'lagra'])
    parser.add_argument('--num_iters', help='total iterations count', type=int, default=1000)

    parser.add_argument('--data_dir', default='/scratch/s/sdraper/tharindu/conce')
    parser.add_argument('--plot', help='plot at the end', action='store_true')
    parser.add_argument('--save', help='save json', action='store_true')
    parser.add_argument('--save_freq', help='save frequency', type=int, default=20)
    parser.add_argument('--loss_eval_freq', help='evaluate global loss frequency', type=int, default=20)

    return parser.parse_args()


if __name__ == '__main__':
    _a = parse_args()
    print('[Arguments]', vars(_a))
    main()
