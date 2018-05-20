import tensorflow as tf
from tensorflow.contrib import layers

from config import MovieQAPath
from raw_input import Input

_mp = MovieQAPath()
hp = {'emb_dim': 300, 'feat_dim': 512, 'dropout_rate': 0.1}


def dropout(x, training):
    return tf.layers.dropout(x, hp['dropout_rate'], training=training)


def l2_norm(x, axis=1):
    return tf.nn.l2_normalize(x, axis=axis)


def unit_norm(x, dim=2):
    return layers.unit_norm(x, dim=dim, epsilon=1e-12)


class Model(object):
    def __init__(self, data, beta=0.0, training=False):
        self.data = data
        reg = layers.l2_regularizer(beta)
        initializer = tf.glorot_normal_initializer(seed=0)

        # constraint = tf.keras.constraints.NonNeg()
        def dense(x, units, activation=None, reuse=False, drop=True, use_bias=True, norm=True, skip=False):
            xx = x
            x = tf.layers.dense(x, units, activation, use_bias=use_bias,  # kernel_constraint=constraint,
                                kernel_initializer=initializer, kernel_regularizer=reg,
                                reuse=reuse)
            if skip:
                x = x + xx
            if norm:
                x = l2_norm(x)
            if drop:
                x = dropout(x, training)
            return x

        with tf.variable_scope('Embedding_Linear'):
            self.raw_ques = self.data.ques
            self.raw_ans = self.data.ans
            # self.raw_subt = self.data.subt
            self.raw_feat = tf.boolean_mask(self.data.feat, tf.cast(self.data.spec, tf.bool))

            # self.raw_subt = tf.boolean_mask(self.data.subt, tf.cast(self.data.spec, tf.bool))
            self.raw_ques = l2_norm(self.raw_ques)
            self.raw_ans = l2_norm(self.raw_ans)
            # self.raw_subt = l2_norm(self.raw_subt)
            # self.raw_feat = l2_norm(self.raw_feat)

            # (5, E_t)
            self.ans = dense(self.raw_ans, hp['emb_dim'],
                             # tf.nn.tanh,
                             # norm=False,
                             # drop=False,
                             # skip=True
                             )

            # (N, E_t)
            # self.subt = dense(self.raw_subt, hp['emb_dim'],
            #                   tf.nn.tanh,
            #                   # norm=False,
            #                   # drop=False,
            #                   skip=True
            #                   )
            # (1, E_t)
            self.ques = dense(self.raw_ques, hp['emb_dim'],
                              # tf.nn.tanh,
                              # norm=False,
                              # drop=False,
                              # skip=True
                              )
            # (N, 4, 4, E_t)
            self.feat = tf.layers.conv2d(self.raw_feat, hp['emb_dim'], [8, 8],
                                         kernel_initializer=initializer, kernel_regularizer=reg,
                                         # activation=tf.nn.tanh,
                                         )
            self.feat = tf.reduce_mean(self.feat, axis=[1, 2])
            # (N, 16, E_t)
            # self.feat = tf.reshape(self.feat, [-1, 16, hp['emb_dim']])

        # with tf.variable_scope('Features'):
        #     # (N, 16, 1)
        #     self.fq = tf.tensordot(self.feat, self.ques, axes=[[2], [1]])
        #     # self.fq = tf.nn.relu(self.fq)
        #     # (N, 16, 5)
        #     # self.fa = tf.matmul(self.feat, self.ans, transpose_b=True)
        #     # self.fa = tf.nn.relu(self.fa)
        #     # (N, 16, 5)
        #     # self.spt_attn = self.fq * self.fa
        #     # self.spt_attn = dropout(self.spt_attn, training)
        #     # # (1, N, 16, 5)
        #     # self.spt_attn = tf.expand_dims(self.spt_attn, 0)
        #     # # (5, N, 16, 1)
        #     # self.spt_attn = tf.transpose(self.spt_attn, [3, 1, 2, 0])
        #     # # (5, N, 16, E_t)
        #     # self.spt_abs = tf.expand_dims(self.feat, 0) * self.spt_attn
        #     # # (5, N, E_t)
        #     # self.spt_abs = tf.reduce_sum(self.spt_abs, axis=2)
        #     # self.spt_abs = l2_norm(self.spt_abs, axis=2)
        #     # (N, 16, 1)
        #     self.spt_attn = self.fq
        #     self.spt_attn = dropout(self.spt_attn, training)
        #     # (N, 16, E_t)
        #     self.spt_abs = self.feat * self.spt_attn
        #     # (N, E_t)
        #     self.spt_abs = tf.reduce_sum(self.spt_abs, axis=1)
        #     # (N, E_t)
        #     self.spt_abs = l2_norm(self.spt_abs, axis=1)

        with tf.variable_scope('IDK'):
            # self.subt = tf.concat([self.subt, self.spt_abs], axis=1)
            # self.subt = dense(self.subt, hp['emb_dim'],
            #                   tf.nn.tanh,
            #                   )
            self.subt = self.feat

        with tf.variable_scope('Response'):
            # (N, 1)
            self.sq = tf.matmul(self.subt, self.ques, transpose_b=True)
            self.sq = tf.nn.relu(self.sq)
            # (N, 5)
            self.sa = tf.matmul(self.subt, self.ans, transpose_b=True)
            self.sa = tf.nn.relu(self.sa)
            # (N, 5)
            self.attn = self.sq + self.sa
            # self.attn = dropout(self.attn, training)
            # (1, N, 5)
            self.attn = tf.expand_dims(self.attn, 0)
            # (5, N, 1)
            self.attn = tf.transpose(self.attn, [2, 1, 0])
            # (5, N, E_t)
            self.abs = tf.expand_dims(self.subt, 0) * self.attn
            # (5, E_t)
            self.abs = tf.reduce_sum(self.abs, axis=1)
            self.abs = l2_norm(self.abs, 1)
            # (5, 1)
            self.output = tf.reduce_sum(self.abs * self.ans, axis=1, keepdims=True)
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
        a, b = sess.run([model.subt, model.output])
        print(a, b)
        print(a.shape, b.shape)


if __name__ == '__main__':
    main()
