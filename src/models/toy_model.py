import tensorflow as tf
import numpy as np

from . import model
from . import strategy


model.datasets.put('toy_model', 1)
model.add_arg(('toy_sigma2', {'help':'variance within distributions', 'type':float}))

'''
definitions for distribution strategies
'''
reg_dist = strategy.reg_stg


class Dist:
    def __init__(self, mu, sigma2, label):
        self.mu = mu
        self.cov = np.eye(len(mu))*sigma2*len(mu)
        self.label = label

    def sample(self, size):
        if size<=0: size = 10000
        x_ = np.random.multivariate_normal(self.mu, self.cov, size)
        y_ = np.ones(size, dtype=int)*self.label
        return (x_, y_)


class QGlobal:
    def __init__(self, locals):
        self.locals = locals

    def sample(self, size):
        assert(size<0)
        xys = [local.sample(size) for local in self.locals]
        xl, yl = zip(*xys)
        return (np.vstack(xl), np.vstack(yl))


def plot_distrb(locals, Q_global):
    import matplotlib.pyplot as plt

    def plot(dst,sz):
        x1,x2 = dst.sample(sz)[0].T
        plt.scatter(x1,x2, marker='.')

    plot(Q_global, -1)
    for loc in locals: plot(loc, 500)

    plt.gca().set_aspect('equal', 'box')
    plt.grid()
    plt.show()


def require(*arg_names):
    def inner(func):
        def wrapper(*args, **kwargs):
            for name in arg_names:
                if model.arg_dict.get(name, None) is None:
                    raise ValueError('Missing required argument: %s'%name)
            return func(*args, **kwargs)
        return wrapper
    return inner


@require('toy_sigma2')
def distinct_n(mus):
    locals = [Dist(mus[i], model.arg_dict['toy_sigma2'], i) for i in range(len(mus))]
    return locals, QGlobal(locals)

@reg_dist
def toy_2_2(d_): return distinct_n([[1,1], [-1,-1]])

@reg_dist
def toy_4_3(d_): return distinct_n([[1,1,1], [1,-1,-1], [-1,1,-1], [-1,-1,1]])

@reg_dist
def toy_4_2(d_): return distinct_n([[1,0], [0,1], [-1,0], [0,-1]])


def test_distrb():
    model.arg_vals['toy_sigma2'] = 0.1
    dists = distinct_2_2()
    plot_distrb(*dists)
    locals, Q_global = dists
    print(Q_global.sample(-1))
    print(locals[0].sample(5))


'''
definitions for functions
'''
Eval = model.EvalClassification
dense = tf.layers.dense


def reg_func(dim_inp, dim_out):
    def inner(func):
        lam = lambda: Eval(model.var_collector(func), dim_inp, dim_out)
        model.funcs.put(func.__name__, lam)
        return func
    return inner

@reg_func(2,1)
def linear2(x_):
    return dense(x_, 1, activation=None)

@reg_func(3,4)
def linear3(x_):
    return dense(x_, 4, activation=None)

@reg_func(2,4)
def linear4(x_):
    return dense(x_, 4, activation=None)


if __name__ == '__main__': test_distrb()
