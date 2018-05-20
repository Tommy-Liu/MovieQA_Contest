import tensorflow as tf
from tensorflow.contrib import layers

from config import MovieQAPath
from raw_input import Input

_mp = MovieQAPath()
hp = {'emb_dim': 300, 'feat_dim': 512, 'dropout_rate': 0.1}

_BIAS_VARIABLE_NAME = "bias"
_WEIGHTS_VARIABLE_NAME = "kernel"


def dropout(x, training):
    return tf.layers.dropout(x, hp['dropout_rate'], training=training)


def l2_norm(x, axis=1):
    return tf.nn.l2_normalize(x, axis=axis)


def unit_norm(x, dim=2):
    return layers.unit_norm(x, dim=dim, epsilon=1e-12)


def l1_norm(x, axis=None, epsilon=1e-6, name=None):
    with tf.name_scope(name, "l1_normalize", [x]) as name:
        x = tf.convert_to_tensor(x, name="x")
        square_sum = tf.reduce_sum(x, axis, keepdims=True)
        x_inv_norm = tf.reciprocal(tf.maximum(square_sum, epsilon))
        return tf.multiply(x, x_inv_norm, name=name)


def bhattacharyya_norm(x, axis=None, epsilon=1e-6, name=None):
    with tf.name_scope(name, "l1_normalize", [x]) as name:
        x = tf.convert_to_tensor(x, name="x")
        x = tf.sqrt(x)
        square_sum = tf.reduce_sum(x, axis, keepdims=True)
        x_inv_norm = tf.reciprocal(tf.maximum(square_sum, epsilon))
        return tf.multiply(x, x_inv_norm, name=name)


def cond(i, s, q, a, w, v):
    return i < 10


def body(s, q, a, w, v):
    clue = tf.concat([q, v], axis=1)
    pick = tf.nn.relu(tf.matmul(clue, w))
    v = v
    # v = l2_norm(v)
    return s, q, w, v


def scan_fn(a, x):
    # v, w
    x = tf.expand_dims(x, 0)
    clue = tf.concat([x, a[0]], axis=1)
    pick = tf.nn.relu(tf.matmul(clue, a[1]))
    return a[0] + pick * x, a[1]


def iterable(o):
    try:
        iter(o)
        return True
    except TypeError:
        return False


class Model(object):
    def __init__(self, data, scale=0.0, training=False):
        self.data = data
        reg = layers.l2_regularizer(scale)
        init = tf.glorot_normal_initializer(seed=0)

        def distance_matrix(n):
            # gamma = tf.get_variable('gamma', [], initializer=tf.ones_initializer())
            index = tf.expand_dims(tf.range(n), 1)
            index_t = tf.transpose(index)
            dist_mat = tf.abs(index - index_t) + 1
            dist_mat = tf.to_float(dist_mat)
            return tf.sqrt(dist_mat)

        with tf.variable_scope('Embedding_Linear'):
            self.raw_ques = self.data.ques
            self.raw_ans = self.data.ans
            self.raw_subt = self.data.subt
            # self.raw_subt = tf.boolean_mask(self.data.subt, tf.cast(self.data.spec, tf.bool))
            self.raw_ques = l2_norm(self.raw_ques)
            self.raw_ans = l2_norm(self.raw_ans)
            self.raw_subt = l2_norm(self.raw_subt)

            self.raw_ques = dropout(self.raw_ques, training)
            self.raw_ans = dropout(self.raw_ans, training)
            self.raw_subt = dropout(self.raw_subt, training)

            self.spec = tf.cast(self.data.spec, tf.bool)
            self.neg_spec = tf.logical_not(self.spec)

            self.spec = tf.to_int32(self.spec)
            self.neg_spec = tf.to_int32(self.neg_spec)

            self.spec = tf.expand_dims(self.spec, 1)
            self.neg_spec = tf.expand_dims(self.neg_spec, 1)

            self.spec_mask = tf.matmul(self.neg_spec, self.spec, transpose_b=True)
            self.spec_mask = tf.to_float(self.spec_mask)
            # self.spec_mask = tf.cast(self.spec_mask, tf.bool)
            # self.spec_mask = tf.logical_not(self.spec_mask)
            # self.spec_mask = tf.cast(self.spec_mask, tf.float32)
            # self.spec_mask = self.spec_mask * (-2**32 + 1)

            self.spec = tf.cast(self.spec, tf.float32)
            self.neg_spec = tf.cast(self.neg_spec, tf.float32)

            # (5, E_t)
            self.ans = tf.layers.dense(self.raw_ans, hp['emb_dim'],
                                       kernel_initializer=init, kernel_regularizer=reg)
            self.ans = self.ans + self.raw_ans
            self.ans = l2_norm(self.ans)
            self.ans = dropout(self.ans, training)

            # (N, E_t)
            self.subt = tf.layers.dense(self.raw_subt, hp['emb_dim'],  # reuse=True,
                                        kernel_initializer=init, kernel_regularizer=reg)
            self.subt = self.subt + self.raw_subt
            self.subt = l2_norm(self.subt)
            self.subt = dropout(self.subt, training)

            # (1, E_t)
            self.ques = tf.layers.dense(self.raw_ques, hp['emb_dim'],  # reuse=True,
                                        kernel_initializer=init, kernel_regularizer=reg)
            self.ques = self.ques + self.raw_ques
            self.ques = l2_norm(self.ques)
            self.ques = dropout(self.ques, training)

            # num_subt = tf.shape(self.subt)[0]

        with tf.variable_scope('Response'):
            # (N, E_t)
            self.front_subt = tf.layers.dense(self.subt, hp['emb_dim'], use_bias=False,
                                              kernel_initializer=init, kernel_regularizer=reg)
            # self.front_subt = self.subt + self.front_subt
            self.front_subt = l2_norm(self.front_subt)
            self.front_subt = dropout(self.front_subt, training)
            # (N, N)
            # self.dist_mat = distance_matrix(num_subt)
            # (N, N)
            self.propagation = tf.matmul(self.front_subt, self.subt, transpose_b=True)
            self.propagation = tf.nn.relu(self.propagation)
            # self.propagation = self.propagation / self.dist_mat
            self.propagation = self.propagation * self.spec_mask
            num_spec = tf.reduce_sum(self.spec)
            self.belief = tf.matmul(self.propagation, self.spec) / num_spec
            self.belief = dropout(self.belief, training)
            # self.belief = tf.reduce_max(self.propagation, axis=1, keepdims=True)
            self.belief = self.spec + self.belief
            self.belief = tf.minimum(self.belief, 1.0)

            # (N, 1)
            self.sq = tf.matmul(self.subt, self.ques, transpose_b=True)
            self.sq = tf.nn.relu(self.sq)
            self.sq = dropout(self.sq, training)
            # # (N, 5)
            self.sa = tf.matmul(self.subt, self.ans, transpose_b=True)
            self.sa = tf.nn.relu(self.sa)
            self.sa = dropout(self.sa, training)
            beta = tf.nn.sigmoid(tf.get_variable('beta', [], initializer=tf.zeros_initializer()))

            self.attn = self.sq + beta * self.sa
            self.attn = self.attn * self.belief
            self.attn = tf.expand_dims(self.attn, 0)
            # (5, N, 1)
            self.attn = tf.transpose(self.attn, [2, 1, 0])
            # (5, N, E_t)
            self.abs = tf.expand_dims(self.subt, 0) * self.attn
            # (5, E_t)
            self.abs = tf.reduce_sum(self.abs, axis=1)
            alpha = tf.nn.sigmoid(tf.get_variable('alpha', [], initializer=tf.zeros_initializer()))
            self.abs = (1 - alpha) * self.abs + alpha * self.ques
            self.abs = l2_norm(self.abs)
            self.abs = dropout(self.abs, training)
            # self.evd = l2_norm(self.ans)
            # (5, 1)
            self.output = tf.reduce_sum(self.abs * self.ans, axis=1, keepdims=True)
            self.output = self.output - tf.reduce_mean(self.output, axis=0, keepdims=True)
            # (1, 5)
            self.output = tf.transpose(self.output)


def main():
    data = Input(split='train', mode='subt')
    model = Model(data)

    for v in tf.global_variables():
        print(v)
    config = tf.ConfigProto(allow_soft_placement=True)
    config.gpu_options.allow_growth = True
    # config.graph_options.optimizer_options.global_jit_level = tf.OptimizerOptions.ON_1
    with tf.Session(config=config) as sess:
        sess.run([model.data.initializer, tf.global_variables_initializer()],
                 feed_dict=data.feed_dict)

        # q, a, s = sess.run([model.ques_enc, model.ans_enc, model.subt_enc])
        # print(q.shape, a.shape, s.shape)
        # a, b, c, d = sess.run(model.tri_word_encodes)
        # print(a, b, c, d)
        # print(a.shape, b.shape, c.shape, d.shape)
        a, b = sess.run([model.subt, model.abs])
        print(a, b)
        print(a.shape, b.shape)


if __name__ == '__main__':
    main()
