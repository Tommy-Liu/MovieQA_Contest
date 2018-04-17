import argparse
import importlib
import math
import os

import tensorflow as tf
from tensorflow.python import debug as tf_debug
from tqdm import trange

from config import MovieQAPath
# from input import Input as In
# from input_v2 import Input as In2
from raw_input import Input
from utils import func_utils as fu
from utils import model_utils as mu

_mp = MovieQAPath()


class TrainManager(object):
    def __init__(self):

        if reset:
            if os.path.exists(self._checkpoint_dir):
                os.system('rm -rf %s' % self._checkpoint_dir)
            if os.path.exists(self._log_dir):
                os.system('rm -rf %s' % self._log_dir)

        fu.make_dirs(os.path.join(self._checkpoint_dir, 'best'))
        fu.make_dirs(self._log_dir)

        self.train_data = Input(split='train', mode=args.mode)
        self.val_data = Input(split='val', mode=args.mode)
        # self.test_data = TestInput()

        self.train_model = mod.Model(self.train_data, beta=hp['reg'], training=True)
        with tf.variable_scope(tf.get_variable_scope(), reuse=True):
            self.val_model = mod.Model(self.val_data)

        # with tf.variable_scope(tf.get_variable_scope(), reuse=True):
        #     self.test_model = mod.Model(self.test_data, training=False)

        for v in tf.trainable_variables():
            print(v)

        self.main_loss = mu.get_loss(hp['loss'], self.train_data.gt, self.train_model.output)
        self.attn_loss = mu.get_loss('sigmoid', self.train_data.spec, tf.squeeze(self.train_model.attn))
        self.regu_loss = tf.losses.get_regularization_loss()

        self.loss = 0
        if 'main' in target:
            self.loss += self.main_loss
        elif 'attn' in target:
            self.loss += self.attn_loss
        self.loss += self.regu_loss

        self.train_accuracy, self.train_accuracy_update = tf.metrics.accuracy(self.train_data.gt,
                                                                              tf.argmax(self.train_model.output,
                                                                                        axis=1),
                                                                              name='train_accuracy')
        self.train_attn_accuracy, self.train_attn_accuracy_update = tf.metrics.accuracy(self.train_data.spec,
                                                                                        self.train_model.output,
                                                                                        name='train_accuracy')

        self.train_accuracy_initializer = tf.variables_initializer(tf.get_collection(
            tf.GraphKeys.LOCAL_VARIABLES, scope='train_accuracy'))

        self.val_accuracy, self.val_accuracy_update = tf.metrics.accuracy(self.val_data.gt,
                                                                          tf.argmax(self.val_model.output, axis=1),
                                                                          name='val_accuracy')
        self.val_accuracy_initializer = tf.variables_initializer(tf.get_collection(
            tf.GraphKeys.LOCAL_VARIABLES, scope='val_accuracy'))

        self.global_step = tf.train.get_or_create_global_step()

        decay_step = int(hp['decay_epoch'] * len(self.train_data))
        self.learning_rate = mu.get_lr(hp['decay_type'], hp['learning_rate'], self.global_step,
                                       decay_step, hp['decay_rate'])

        self.optimizer = mu.get_opt(hp['opt'], self.learning_rate, decay_step)

        grads_and_vars = self.optimizer.compute_gradients(self.loss)
        gradients, variables = list(zip(*grads_and_vars))
        self.update_ops = tf.get_collection(tf.GraphKeys.UPDATE_OPS)
        with tf.control_dependencies(self.update_ops):
            self.train_op = tf.group(self.optimizer.apply_gradients(grads_and_vars, self.global_step),
                                     self.train_accuracy_update)

        self.saver = tf.train.Saver(tf.global_variables())
        self.best_saver = tf.train.Saver(tf.global_variables())

        # Summary
        train_gv_summaries = []
        for idx, grad in enumerate(gradients):
            if grad is not None:
                train_gv_summaries.append(tf.summary.histogram('gradients/' + variables[idx].name, grad))
                train_gv_summaries.append(tf.summary.histogram(variables[idx].name, variables[idx]))

        train_summaries = [
            tf.summary.scalar('train_loss', self.loss),
            tf.summary.scalar('train_accuracy', self.train_accuracy),
            tf.summary.scalar('learning_rate', self.learning_rate)
        ]
        self.train_summaries_op = tf.summary.merge(train_summaries)
        self.train_gv_summaries_op = tf.summary.merge(train_gv_summaries + train_summaries)

        self.val_summaries_op = tf.summary.scalar('val_accuracy', self.val_accuracy)

        if args.checkpoint:
            self.checkpoint_file = args.checkpoint
        else:
            self.checkpoint_file = tf.train.latest_checkpoint(self._checkpoint_dir)

        self.op_list = [self.train_op, self.loss, self.train_accuracy, self.global_step]
        # self.run_metadata = tf.RunMetadata()

    def train(self):
        config = tf.ConfigProto(allow_soft_placement=True)
        config.gpu_options.allow_growth = True
        # config.graph_options.optimizer_options.global_jit_level = tf.OptimizerOptions.ON_1

        with tf.Session(config=config) as sess, tf.summary.FileWriter(self._log_dir, sess.graph) as sw:
            if debug:
                sess = tf_debug.LocalCLIDebugWrapperSession(sess)
            sess.run([tf.global_variables_initializer(), tf.local_variables_initializer()])

            if self.checkpoint_file:
                print('Restore from', self.checkpoint_file)
                self.saver.restore(sess, self.checkpoint_file)

            summary, acc, max_acc = None, 0, 0

            try:
                while True:
                    step = tf.train.global_step(sess, self.global_step)
                    epoch = math.floor(step / len(self.train_data)) + 1

                    # Train Loop
                    sess.run([self.train_data.initializer, self.train_accuracy_initializer],
                             feed_dict=self.train_data.feed_dict)

                    with trange(epoch * len(self.train_data) - step) as pbar:

                        for _ in pbar:
                            if step % 10000 == 0:
                                _, gv_summary, l, acc, step = sess.run(
                                    [self.train_op, self.train_gv_summaries_op, self.loss, self.train_accuracy,
                                     self.global_step])
                                # options=tf.RunOptions(trace_level=tf.RunOptions.FULL_TRACE),
                                # run_metadata=self.run_metadata)
                                # trace = timeline.Timeline(step_stats=self.run_metadata.step_stats)
                                sw.add_summary(gv_summary, step)
                                self.saver.save(sess, self._checkpoint_file, step)
                                # with open(args.mod + '.timeline.ctf.json', 'w') as trace_file:
                                #     trace_file.write(trace.generate_chrome_trace_format())
                            elif step % 100 == 0:
                                _, summary, l, step, acc = sess.run(
                                    [self.train_op, self.train_summaries_op, self.loss, self.global_step,
                                     self.train_accuracy])
                                sw.add_summary(summary, step)
                            else:
                                _, l, step, acc = sess.run(
                                    [self.train_op, self.loss, self.global_step, self.train_accuracy])
                            pbar.set_description('[%03d] Train loss: %.3f acc: %.2f' % (epoch, l, acc))

                    self.saver.save(sess, self._checkpoint_file, step)

                    # Validation Loop
                    sess.run([self.val_data.initializer, self.val_accuracy_initializer],
                             feed_dict=self.val_data.feed_dict)
                    with trange(len(self.val_data)) as pbar:
                        for _ in pbar:
                            acc, _, summary = sess.run(
                                [self.val_accuracy, self.val_accuracy_update, self.val_summaries_op])
                            pbar.set_description('[%03d] Validation acc: %.2f' % (epoch, acc))
                        sw.add_summary(summary, step)
                    if acc > max_acc:
                        max_acc = acc
                        self.best_saver.save(sess, self._best_checkpoint, step)
            except KeyboardInterrupt:
                self.saver.save(sess, self._checkpoint_file, self.global_step)

    @property
    def _model_name(self):
        return '-'.join([args.mod, args.hp, args.extra])

    @property
    def _log_dir(self):
        return os.path.join(_mp.log_dir, self._model_name)

    @property
    def _checkpoint_dir(self):
        return os.path.join(_mp.checkpoint_dir, self._model_name)

    @property
    def _checkpoint_file(self):
        return os.path.join(self._checkpoint_dir, self._model_name)

    @property
    def _best_checkpoint(self):
        return os.path.join(self._checkpoint_dir, 'best', self._model_name)


def main():
    trainer = TrainManager()
    trainer.train()


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--mod', default='model', help='Model used to train.')
    parser.add_argument('--reset', action='store_true', help='Reset the experiment.')
    parser.add_argument('--debug', action='store_true', help='Debug mode.')
    parser.add_argument('--mode', default='feat+subt', help='Data mode we use.')
    parser.add_argument('--checkpoint', default='', help='Checkpoint file.')
    parser.add_argument('--hp', default='01', help='Hyper-parameters.')
    parser.add_argument('--extra', default='', help='Extra model name.')
    parser.add_argument('--target', default='main+target', help='Train what?')
    # parser.add_argument('--reg', action='store_true', help='Regularize the model.')
    args = parser.parse_args()
    mod = importlib.import_module('model.' + args.mod)
    hp = getattr(importlib.import_module('hp'), 'hp' + args.hp)
    reset = args.reset
    debug = args.debug
    target = args.target
    main()
