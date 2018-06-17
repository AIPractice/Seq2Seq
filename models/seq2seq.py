import tensorflow as tf
import math
from utils.config import GO, EOS


class Seq2SeqModel():
    def __init__(self, config, mode, logger):
        """
        init model
        :param config: config dict
        :param mode: train or inference
        :param logger: logger object
        """
        assert mode.lower() in ['train', 'inference']
        self.mode = mode.lower()
        self.logger = logger
        self.init_config(config)
        self.build_placeholders()
        self.build_encoder()
        self.build_decoder()
        self.build_optimizer()
    
    def init_config(self, config):
        """
        add config to model
        :param config: config dict
        :return: None
        """
        self.config = config
        self.hidden_units = config['hidden_units']
        self.embedding_size = config['embedding_size']
        self.encoder_max_time_steps = config['encoder_max_time_steps']
        self.decoder_max_time_steps = config['decoder_max_time_steps']
        self.encoder_depth = config['encoder_depth']
        self.decoder_depth = config['decoder_depth']
        self.encoder_vocab_size = config['encoder_vocab_size']
        self.decoder_vocab_size = config['decoder_vocab_size']
        self.logger_name = config['logger_name']
        self.dropout_rate = config['dropout_rate']
        self.dtype = tf.float16 if config['use_fp16'] else tf.float32
        self.optimizer_type = config['optimizer_type']
        self.learning_rate = config['learning_rate']
        self.max_gradient_norm = config['max_gradient_norm']
        self.use_bidirectional = config['use_bidirectional']
        self.use_dropout = config['use_dropout']
        self.global_step = tf.Variable(0, trainable=False, name='global_step')
        self.global_epoch_step = tf.Variable(0, trainable=False, name='global_epoch_step')
        self.global_epoch_step_op = tf.assign(self.global_epoch_step, tf.add(self.global_epoch_step, 1))
    
    def build_placeholders(self):
        """
        init placeholders
        :return: None
        """
        self.keep_prob = tf.placeholder(self.dtype, shape=[], name='keep_prob')
        
        # encoder_inputs: [batch_size, max_time_steps]
        self.encoder_inputs = tf.placeholder(dtype=tf.int32, shape=[None, None],
                                             name='encoder_inputs')
        self.logger.debug('encoder_inputs %s', self.encoder_inputs)
        
        # encoder_inputs_length: [batch_size]
        self.encoder_inputs_length = tf.placeholder(dtype=tf.int32, shape=[None],
                                                    name='encoder_inputs_length')
        self.logger.debug('encoder_inputs_length %s', self.encoder_inputs_length)
        
        # batch_size
        self.batch_size = tf.shape(self.encoder_inputs)[0]
        self.logger.debug('batch_size %s', self.batch_size)
        
        if self.mode == 'train':
            
            # decoder_inputs: [batch_size, max_time_steps]
            self.decoder_inputs = tf.placeholder(dtype=tf.int32, shape=[None, None],
                                                 name='decoder_inputs')
            self.logger.debug('decoder_inputs %s', self.decoder_inputs)
            
            # decoder_inputs_length: [batch_size]
            self.decoder_inputs_length = tf.placeholder(dtype=tf.int32, shape=[None],
                                                        name='decoder_inputs_length')
            self.logger.debug('decoder_inputs_length %s', self.decoder_inputs_length)
            
            # decoder_start_token: [batch_size, 1]
            self.decoder_start_token = tf.ones(shape=[self.batch_size, 1], dtype=tf.int32) * GO
            self.logger.debug('decoder_start_token %s', self.decoder_start_token)
            
            # decoder_end_token: [batch_size, 1]
            self.decoder_end_token = tf.ones(shape=[self.batch_size, 1], dtype=tf.int32) * EOS
            self.logger.debug('decoder_end_token %s', self.decoder_end_token)
            
            # decoder_inputs_train: [batch_size, max_time_steps + 1]
            self.decoder_inputs_train = tf.concat([self.decoder_start_token, self.decoder_inputs], axis=-1)
            self.logger.debug('decoder_inputs_train %s', self.decoder_inputs_train)
            
            # decoder_inputs_train_length: [batch_size]
            self.decoder_inputs_train_length = self.decoder_inputs_length + 1
            self.logger.debug('decoder_inputs_train_length %s', self.decoder_inputs_train_length)
            
            # decoder_targets_train: [batch_size, max_time_steps + 1]
            self.decoder_targets_train = tf.concat([self.decoder_inputs, self.decoder_end_token], axis=-1)
            self.logger.debug('decoder_targets_train %s', self.decoder_targets_train)
            
            # decoder_targets_length: [batch_size]
            self.decoder_targets_train_length = self.decoder_inputs_length + 1
            self.logger.debug('decoder_targets_train_length %s', self.decoder_targets_train_length)
        
        else:
            self.decoder_inputs = tf.ones(shape=[self.batch_size, 1], dtype=tf.int32, name='decoder_inputs') * GO
            self.logger.debug('decoder_inputs %s', self.decoder_inputs)
            
            self.decoder_inputs_inference = self.decoder_inputs
            self.logger.debug('decoder_inputs_inference %s', self.decoder_inputs_inference)
            
            self.decoder_inputs_inference_length = tf.ones(shape=[self.batch_size], dtype=tf.int32,
                                                           name='decoder_inputs_inference_length')
            self.logger.debug('decoder_inputs_inference_length %s', self.decoder_inputs_inference_length)
    
    def build_single_cell(self):
        """
        build single cell, lstm or gru or RNN
        :return: GRUCell or LSTMCell or RNNCell
        """
        cell = tf.nn.rnn_cell.GRUCell(self.hidden_units, name='single_cell')
        if self.use_dropout:
            cell = tf.nn.rnn_cell.DropoutWrapper(cell=cell, dtype=self.dtype, output_keep_prob=self.keep_prob)
        return cell
    
    def build_encoder_cell(self, depth=None):
        """
        build encoder multi cell
        :param depth: encoder depth
        :return: MultiRNNCell
        """
        depth = depth if depth else self.encoder_depth
        cells = [self.build_single_cell() for _ in range(depth)]
        return tf.nn.rnn_cell.MultiRNNCell(cells=cells)
    
    def build_decoder_cell(self, depth=None):
        """
        build decoder multi cell
        :param depth: decoder depth
        :return: MultiRNNCell
        """
        depth = depth if depth else self.decoder_depth
        cells = [self.build_single_cell() for _ in range(depth)]
        return tf.nn.rnn_cell.MultiRNNCell(cells=cells)
    
    def build_encoder(self):
        """
        build encoder
        :return: None
        """
        with tf.variable_scope('encoder') as scope:
            # encoder_embeddings: [encoder_vocab_size, embedding_size]
            self.encoder_embeddings = tf.get_variable(name='embedding',
                                                      shape=[self.encoder_vocab_size, self.embedding_size],
                                                      dtype=self.dtype,
                                                      initializer=tf.random_uniform_initializer(-math.sqrt(3),
                                                                                                math.sqrt(3),
                                                                                                dtype=self.dtype))
            self.logger.debug('encoder_embeddings %s', self.encoder_embeddings)
            
            # encoder_inputs_embedded : [batch_size, encoder_time_steps, embedding_size]
            self.encoder_inputs_embedded = tf.nn.embedding_lookup(params=self.encoder_embeddings,
                                                                  ids=self.encoder_inputs,
                                                                  name='inputs_embedded')
            self.logger.debug('encoder_inputs_embedded %s', self.encoder_inputs_embedded)
            
            # encoder_inputs_embedded_dense: [batch_size, encoder_time_steps, hidden_units]
            self.encoder_inputs_embedded_dense = tf.layers.dense(inputs=self.encoder_inputs_embedded,
                                                                 units=self.hidden_units,
                                                                 use_bias=False,
                                                                 name='inputs_embedded_dense')
            self.logger.debug('encoder_inputs_embedded_dense %s', self.encoder_inputs_embedded_dense)
            
            if self.use_bidirectional:
                # cell forward
                cell_fw = self.build_single_cell()
                # cell backward
                cell_bw = self.build_single_cell()
                
                bi_outputs, bi_last_state = tf.nn.bidirectional_dynamic_rnn(cell_fw=cell_fw,
                                                                            cell_bw=cell_bw,
                                                                            inputs=self.encoder_inputs_embedded_dense,
                                                                            sequence_length=self.encoder_inputs_length,
                                                                            dtype=self.dtype,
                                                                            scope=scope)
                self.logger.debug('bi_outputs %s', bi_outputs)
                self.logger.debug('bi_last_state %s', bi_last_state)
                # concat bi outputs
                bi_outputs = tf.layers.dense(inputs=tf.concat(bi_outputs, axis=-1), units=self.hidden_units,
                                             use_bias=False)
                self.logger.debug('bi_outputs %s', bi_outputs)
                
                if self.encoder_depth > 2:
                    upper_cell = self.build_encoder_cell(self.encoder_depth - 1)
                elif self.encoder_depth == 2:
                    upper_cell = self.build_single_cell()
                else:
                    upper_cell = None
                
                self.logger.debug('upper_cell %s', upper_cell)
                
                if upper_cell:
                    # encoder depth >= 2
                    upper_outputs, upper_last_state = tf.nn.dynamic_rnn(cell=upper_cell, inputs=bi_outputs,
                                                                        sequence_length=self.encoder_inputs_length,
                                                                        dtype=self.dtype,
                                                                        scope=scope)
                    self.logger.debug('upper_outputs %s', upper_outputs)
                    self.logger.debug('upper_last_state %s', upper_last_state)
                    
                    # encoder_outputs: [batch_size, encoder_time_steps, hidden_units]
                    self.encoder_outputs = upper_outputs
                    self.logger.debug('encoder_outputs %s', self.encoder_outputs)
                    
                    # encoder_last_state: [batch_size, hidden_units] * encoder_depth
                    self.encoder_last_state = (bi_last_state[0],) + (
                        (upper_last_state,) if self.encoder_depth == 2 else upper_last_state)
                    self.logger.debug('encoder_last_state %s', self.encoder_last_state)
                else:
                    # encoder_outputs: [batch_size, encoder_time_steps, hidden_units]
                    self.encoder_outputs = bi_outputs
                    self.logger.debug('encoder_outputs %s', self.encoder_outputs)
                    
                    # encoder_last_state: [batch_size, hidden_units] * encoder_depth
                    self.encoder_last_state = (bi_last_state[0],)
                    self.logger.debug('encoder_last_state %s', self.encoder_last_state)
            
            else:
                # encoder_cell
                self.encoder_cell = self.build_encoder_cell()
                self.logger.debug('encoder_cell %s', self.encoder_cell)
                # encoder_outputs: [batch_size, encoder_time_steps, hidden_units]
                # encoder_last_state: [batch_size, hidden_units] * encoder_depth
                self.encoder_outputs, self.encoder_last_state = tf.nn.dynamic_rnn(cell=self.encoder_cell,
                                                                                  inputs=self.encoder_inputs_embedded_dense,
                                                                                  sequence_length=self.encoder_inputs_length,
                                                                                  dtype=self.dtype, scope=scope)
                self.logger.debug('encoder_outputs %s', self.encoder_outputs)
                self.logger.debug('encoder_last_state %s', self.encoder_last_state)
    
    def build_decoder(self):
        """
        build decoder
        :return: None
        """
        with tf.variable_scope('decoder') as scope:
            # decoder_initial_state: [batch_size, hidden_units]
            self.decoder_initial_state = self.encoder_last_state
            self.logger.debug('decoder_initial_state %s', self.decoder_initial_state)
            
            self.decoder_cell = self.build_decoder_cell()
            self.logger.debug('decoder_cell %s', self.decoder_cell)
            
            # decoder_embeddings: [decoder_vocab_size, embedding_size]
            self.decoder_embeddings = tf.get_variable(name='embedding',
                                                      shape=[self.decoder_vocab_size, self.embedding_size],
                                                      dtype=self.dtype,
                                                      initializer=tf.random_uniform_initializer(-math.sqrt(3),
                                                                                                math.sqrt(3),
                                                                                                dtype=self.dtype))
            self.logger.debug('decoder_embeddings %s', self.decoder_embeddings)
            
            if self.mode == 'train':
                # decoder_inputs_embedded: [batch_size, decoder_time_steps, embedding_size]
                self.decoder_inputs_embedded = tf.nn.embedding_lookup(params=self.decoder_embeddings,
                                                                      ids=self.decoder_inputs_train)
                self.logger.debug('decoder_inputs_embedded %s', self.decoder_inputs_embedded)
                
                # decoder_outputs: [batch_size, decoder_time_steps, hidden_units]
                # decoder_last_state: [batch_size, hidden_units]
                self.decoder_outputs, self.decoder_last_state = tf.nn.dynamic_rnn(cell=self.decoder_cell,
                                                                                  initial_state=self.decoder_initial_state,
                                                                                  inputs=self.decoder_inputs_embedded,
                                                                                  sequence_length=self.decoder_inputs_train_length,
                                                                                  dtype=self.dtype,
                                                                                  scope=scope)
                # decoder_logits: [batch_size, decoder_max_time_steps, decoder_vocab_size]
                self.decoder_logits = tf.layers.dense(inputs=self.decoder_outputs,
                                                      units=self.decoder_vocab_size,
                                                      name='decoder_logits')
                self.logger.debug('decoder_logits %s', self.decoder_logits)
                
                # decoder_masks: [batch_size, reduce_max(decoder_inputs_length)]
                self.decoder_masks = tf.sequence_mask(lengths=self.decoder_inputs_train_length,
                                                      maxlen=tf.reduce_max(self.decoder_targets_train_length),
                                                      dtype=self.dtype,
                                                      name='masks')
                self.logger.debug('decoder_masks %s', self.decoder_masks)
                
                # loss
                self.loss = tf.contrib.seq2seq.sequence_loss(logits=self.decoder_logits,
                                                             targets=self.decoder_targets_train,
                                                             weights=self.decoder_masks)
                self.logger.debug('loss %s', self.loss)
            
            else:
                
                # decoder_initial_tokens: [batch_size]
                self.decoder_initial_tokens = tf.ones(shape=[self.batch_size], dtype=tf.int32,
                                                      name='initial_tokens') * GO
                self.logger.debug('decoder_initial_tokens %s', self.decoder_initial_tokens)
                
                # decoder_initial_tokens_embedded: [batch_size, embedding_size]
                self.decoder_initial_tokens_embedded = tf.nn.embedding_lookup(params=self.decoder_embeddings,
                                                                              ids=self.decoder_initial_tokens)
                self.logger.debug('decoder_initial_tokens_embedded %s', self.decoder_initial_tokens_embedded)
                
                self.decoder_outputs = []
                self.decoder_logits = []
                self.decoder_probabilities = []
                self.decoder_predicts = []
                self.decoder_scores = []
                
                # initial state and input
                state = self.decoder_initial_state
                # input: [batch_size, embedding_size]
                input = self.decoder_initial_tokens_embedded
                
                # decoder loop
                for _ in range(self.decoder_max_time_steps):
                    # decode one step
                    # input: [batch_size, embedding_size]
                    # state:
                    output, state = self.decoder_cell(
                        inputs=input,
                        state=state)
                    
                    logits = tf.layers.dense(inputs=output,
                                             units=self.decoder_vocab_size,
                                             name='decoder_logits', reuse=tf.AUTO_REUSE)
                    # probability matrix
                    probabilities = tf.nn.softmax(logits, -1)
                    
                    # argmax index
                    predicts = tf.argmax(probabilities, -1)
                    
                    # argmax probability score
                    scores = tf.reduce_max(probabilities, -1)
                    
                    # next input
                    input = tf.nn.embedding_lookup(params=self.decoder_embeddings,
                                                   ids=predicts)
                    
                    self.decoder_last_state = state
                    self.decoder_outputs.append(output)
                    self.decoder_logits.append(logits)
                    self.decoder_probabilities.append(probabilities)
                    self.decoder_predicts.append(predicts)
                    self.decoder_scores.append(scores)
                
                self.decoder_outputs = tf.stack(self.decoder_outputs, axis=1)
                self.decoder_logits = tf.stack(self.decoder_logits, axis=1)
                self.decoder_probabilities = tf.stack(self.decoder_probabilities, axis=1)
                self.decoder_predicts = tf.stack(self.decoder_predicts, axis=1)
                self.decoder_scores = tf.stack(self.decoder_scores, axis=1)
                
                self.logger.debug('decoder_logits %s', self.decoder_logits)
                self.logger.debug('decoder_probabilities %s', self.decoder_probabilities)
                self.logger.debug('decoder_predicts %s', self.decoder_predicts)
                self.logger.debug('decoder_last_state %s', self.decoder_last_state)
                self.logger.debug('decoder_scores %s', self.decoder_scores)
    
    def build_optimizer(self):
        """
        build optimizer
        :return: None
        """
        if self.mode == 'train':
            self.logger.info('Setting optimizer...')
            
            # trainable_verbs
            self.trainable_verbs = tf.trainable_variables()
            # self.logger.debug('trainable_verbs %s', self.trainable_verbs)
            
            if self.optimizer_type.lower() == 'adam':
                self.optimizer = tf.train.AdamOptimizer(learning_rate=self.learning_rate)
                self.logger.info('Optimizer has been set')
            
            # compute gradients
            self.gradients = tf.gradients(ys=self.loss, xs=self.trainable_verbs)
            
            # clip gradients by a given maximum_gradient_norm
            self.clip_gradients, _ = tf.clip_by_global_norm(self.gradients, self.max_gradient_norm)
            
            # train op
            self.train_op = self.optimizer.apply_gradients(zip(self.clip_gradients, self.trainable_verbs),
                                                           global_step=self.global_step)
    
    def save(self, sess, save_path, var_list=None, global_step=None):
        """
        save model to ckpt
        :param sess: session object
        :param save_path: save path
        :param var_list: variables list
        :param global_step: global step
        :return: None
        """
        saver = tf.train.Saver(var_list)
        
        # save model
        saver.save(sess=sess, save_path=save_path, global_step=global_step)
        self.logger.info('model saved at %s', save_path)
    
    def restore(self, sess, save_path, var_list=None):
        """
        restore model from ckpt
        :param sess: session object
        :param save_path: save path
        :param var_list: variables list
        :return: None
        """
        saver = tf.train.Saver(var_list)
        saver.restore(sess=sess, save_path=save_path)
        self.logger.info('model restored from %s', save_path)
    
    def train(self, sess, encoder_inputs, encoder_inputs_length,
              decoder_inputs, decoder_inputs_length):
        """
        train process
        :param sess: session object
        :param encoder_inputs:
        :param encoder_inputs_length:
        :param decoder_inputs:
        :param decoder_inputs_length:
        :return: None
        """
        input_feed = {
            self.encoder_inputs.name: encoder_inputs,
            self.encoder_inputs_length.name: encoder_inputs_length,
            self.decoder_inputs.name: decoder_inputs,
            self.decoder_inputs_length.name: decoder_inputs_length,
            self.keep_prob.name: 1 - self.dropout_rate
        }
        
        output_feed = [
            self.loss,
            self.train_op,
        ]
        outputs = sess.run(fetches=output_feed, feed_dict=input_feed)
        return outputs
    
    def eval(self, sess, encoder_inputs, encoder_inputs_length,
             decoder_inputs, decoder_inputs_length):
        """
        eval process
        :param sess: session object
        :param encoder_inputs:
        :param encoder_inputs_length:
        :param decoder_inputs:
        :param decoder_inputs_length:
        :return: None
        """
        input_feed = {
            self.encoder_inputs.name: encoder_inputs,
            self.encoder_inputs_length.name: encoder_inputs_length,
            self.decoder_inputs.name: decoder_inputs,
            self.decoder_inputs_length.name: decoder_inputs_length,
            self.keep_prob.name: 1
        }
        
        output_feed = self.loss
        
        outputs = sess.run(fetches=output_feed, feed_dict=input_feed)
        return outputs
    
    def inference(self, sess, encoder_inputs, encoder_inputs_length):
        """
        inference process
        :param sess: session object
        :param encoder_inputs:
        :param encoder_inputs_length:
        :return: None
        """
        input_feed = {
            self.encoder_inputs.name: encoder_inputs,
            self.encoder_inputs_length.name: encoder_inputs_length,
            self.keep_prob.name: 1
        }
        
        output_feed = [
            self.decoder_predicts,
            self.decoder_scores,
        ]
        outputs = sess.run(fetches=output_feed, feed_dict=input_feed)
        return outputs
