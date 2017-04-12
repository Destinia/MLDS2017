import tensorflow as tf
import numpy as np
import random

class S2VT_model():
    
    def __init__(self, frame_steps=80, frame_feat_dim=4096, caption_steps=45, vocab_size=3000, dim_hidden=300, schedule_sampling_converge=500):
        

        self.frame_steps = frame_steps
        self.frame_feat_dim = frame_feat_dim
        self.caption_steps = caption_steps
        self.vocab_size = vocab_size
        self.dim_hidden = dim_hidden
        self.schedule_sampling_converge = schedule_sampling_converge

        ## Graph input
        self.frame = tf.placeholder(tf.float32, [None, frame_steps, frame_feat_dim])
        self.caption = tf.placeholder(tf.int32, [None, caption_steps+1])
        self.caption_mask = tf.placeholder(tf.float32, [None, caption_steps+1])
        batch_frame = tf.shape(self.frame)[0]
        batch_caption = tf.shape(self.caption)[0]
        tf.Assert(tf.equal(batch_frame, batch_caption), [batch_frame, batch_caption])
        batch_size = batch_frame
        self.train_state = tf.placeholder(tf.bool)

        
        ## frame Embedding param 
        with tf.variable_scope("frame_embedding"):
            w_frame_embed = tf.get_variable("w_frame_embed", [frame_feat_dim, dim_hidden], initializer= tf.contrib.layers.xavier_initializer(dtype=tf.float32))
            b_frame_embed = tf.get_variable("b_frame_embed", [dim_hidden], initializer=tf.constant_initializer(0.0))
        
        ## word embedding param
        with tf.device("/cpu:0"):
            embedding = tf.get_variable("embedding", [vocab_size, dim_hidden], dtype=tf.float32)
        
        ## word embedding to onehot param
        w_word_onehot = tf.get_variable("w_word_onehot", [dim_hidden, vocab_size], initializer=tf.contrib.layers.xavier_initializer(dtype=tf.float32))
        b_word_onehot = tf.get_variable("b_word_onehot", [vocab_size], initializer=tf.constant_initializer(0.0))
        
        ## two lstm param
        with tf.variable_scope("att_lstm"):
            att_lstm = tf.contrib.rnn.LSTMCell(dim_hidden)
        with tf.variable_scope("cap_lstm"):
            cap_lstm = tf.contrib.rnn.LSTMCell(dim_hidden)
        
        att_state = (tf.zeros([batch_size, dim_hidden]),tf.zeros([batch_size, dim_hidden]))
        cap_state = (tf.zeros([batch_size, dim_hidden]),tf.zeros([batch_size, dim_hidden]))
        
        padding = tf.zeros([batch_size, dim_hidden])
        
        ##################### Computing Graph ########################
        
        frame_flat = tf.reshape(self.frame, [-1, frame_feat_dim])
        frame_embedding = tf.nn.xw_plus_b( frame_flat, w_frame_embed, b_frame_embed )
        frame_embedding = tf.reshape(frame_embedding, [batch_size, frame_steps, dim_hidden])        
        
        
        cap_lstm_outputs = []
        
        ## Encoding stage
        for i in range(frame_steps):
            with tf.variable_scope('att_lstm'):
                if i > 0:
                    tf.get_variable_scope().reuse_variables()
                output1, att_state = att_lstm(frame_embedding[:,i,:], att_state)
            ##input shape of cap_lstm2: [batch_size, 2*dim_hidden]
            with tf.variable_scope('cap_lstm'):
                if i > 0:
                    tf.get_variable_scope().reuse_variables()
                output2, cap_state = cap_lstm(tf.concat([padding, output1], 1), cap_state)
        
        ## Decoding stage
        ## Training util
        def train_cap(prev_endcoder_output, prev_decoder_output, prev_state):
            with tf.device('/cpu:0'):
                word_embed = tf.nn.embedding_lookup(embedding, prev_decoder_output)
                output, state = cap_lstm(
                    tf.concat([word_embed, prev_endcoder_output], 1), prev_state)
                m_state, c_state = state
                return output, m_state, c_state
        def test_cap(prev_encoder_output, prev_decoder_output, prev_state):
            ##  TODO: beam search
            word_index = tf.argmax(prev_decoder_output, axis=1)
            word_embed = tf.nn.embedding_lookup(embedding, word_index)
            output, state = cap_lstm(
                tf.concat([word_embed, prev_encoder_output], 1), prev_state)
            m_state, c_state = state
            return output, m_state, c_state
        output2 = tf.tile(tf.one_hot([4], vocab_size), [batch_size, 1])
        for i in range(caption_steps):
            
            with tf.variable_scope('att_lstm'):
                tf.get_variable_scope().reuse_variables()
                output1, att_state = att_lstm(padding, att_state)
                        
            with tf.variable_scope('cap_lstm'):
                tf.get_variable_scope().reuse_variables()
                    
                # output2, cap_state = test_cap(output1, output2, cap_state)

                output2, m_state, c_state = tf.cond(self.train_state, lambda: train_cap(output1, self.caption[:,i], cap_state), lambda: test_cap(output1, output2, cap_state))
                cap_state = (m_state, c_state)
                cap_lstm_outputs.append(output2)
                
        


        output = tf.reshape(tf.concat(cap_lstm_outputs , 1), [-1, dim_hidden]) 

        ## shape (batch_size*caption_steps, vocab_size)               
        onehot_word_logits = tf.nn.xw_plus_b(output, w_word_onehot, b_word_onehot)
        self.predict_result = tf.reshape(tf.argmax(onehot_word_logits[:,2:], 1)+2, [batch_size, caption_steps])
        
        loss = tf.contrib.legacy_seq2seq.sequence_loss_by_example([onehot_word_logits],
                                                                  [tf.reshape(self.caption[:,1:], [-1])],
                                                                  [tf.reshape(self.caption_mask[:,1:], [-1])])
        
        self.cost = tf.reduce_mean(loss)
        self.global_step = tf.Variable(0, trainable=False)
        self.train_op = tf.train.AdamOptimizer().minimize(self.cost, global_step=self.global_step)
        
        config = tf.ConfigProto(log_device_placement = True)
        config.gpu_options.allow_growth = True
        
        self.sess = tf.Session(config=config)

    def train(self, input_frame, input_caption,input_caption_mask, keep_prob=0.5):
        _,cost = self.sess.run([self.train_op,self.cost],feed_dict={self.frame:input_frame, 
                                                                    self.caption:input_caption, 
                                                                    self.caption_mask:input_caption_mask,
                                                                    self.train_state:True})
        return cost
   
    def predict(self, input_frame):
        padding = np.zeros([input_frame.shape[0], self.caption_steps + 1])
        words = self.sess.run([self.predict_result], feed_dict={self.frame: input_frame,
                                                                self.caption: padding,
                                                                self.train_state: False})
        return words
    def initialize(self):
        self.sess.run(tf.global_variables_initializer())
    
    def schedule_sampling(self):
        prob = self.global_step / self.schedule_sampling_converge
        return random.random() > prob


class S2VT_attention_model():
    
    def __init__(self, batch_size=20, frame_steps=80, frame_feat_dim=4096, caption_steps=45, vocab_size=3000, dim_hidden=300):
        
        self.batch_size = batch_size
        self.frame_steps = frame_steps
        self.frame_feat_dim = frame_feat_dim
        self.caption_steps = caption_steps
        self.vocab_size = vocab_size
        self.dim_hidden = dim_hidden
    
        ## Graph input
        self.frame = tf.placeholder(tf.float32, [batch_size, frame_steps, frame_feat_dim])    
        self.caption = tf.placeholder(tf.int32, [batch_size, caption_steps+1])
        self.caption_mask = tf.placeholder(tf.float32, [batch_size, caption_steps+1])
        
        ## frame Embedding param 
        with tf.variable_scope("frame_embedding"):
            w_frame_embed = tf.get_variable("w_frame_embed", [frame_feat_dim, dim_hidden], initializer= tf.contrib.layers.xavier_initializer(dtype=tf.float32))
            b_frame_embed = tf.get_variable("b_frame_embed", [dim_hidden], initializer=tf.constant_initializer(0.0))
        
        ## word embedding param
        with tf.device("/cpu:0"):
            embedding = tf.get_variable("embedding", [vocab_size, dim_hidden], dtype=tf.float32)
        
        ## word embedding to onehot param
        w_word_onehot = tf.get_variable("w_word_onehot", [dim_hidden, vocab_size], initializer=tf.contrib.layers.xavier_initializer(dtype=tf.float32))
        b_word_onehot = tf.get_variable("b_word_onehot", [vocab_size], initializer=tf.constant_initializer(0.0))
        
        ## two lstm param
        with tf.variable_scope("att_lstm"):
            att_lstm = tf.contrib.rnn.LSTMCell(dim_hidden)
        with tf.variable_scope("cap_lstm"):
            cap_lstm = tf.contrib.rnn.LSTMCell(dim_hidden)            
        
        att_state = (tf.zeros([batch_size, dim_hidden]),tf.zeros([batch_size, dim_hidden]))
        cap_state = (tf.zeros([batch_size, dim_hidden]),tf.zeros([batch_size, dim_hidden]))
        
        padding = tf.zeros([batch_size, dim_hidden])
        
        ##################### Computing Graph ########################
        
        frame_flat = tf.reshape(self.frame, [-1, frame_feat_dim])
        frame_embedding = tf.nn.xw_plus_b( frame_flat, w_frame_embed, b_frame_embed )
        frame_embedding = tf.reshape(frame_embedding, [batch_size, frame_steps, dim_hidden])        
        
        
        cap_lstm_outputs = []
        
        ## Encoding stage
        for i in range(frame_steps):

            with tf.variable_scope('att_lstm'):
                if i > 0:
                    tf.get_variable_scope().reuse_variables()
                    output1, att_state = att_lstm(frame_embedding[:,i,:], att_state)
                else:
                    output1, att_state = att_lstm(frame_embedding[:,i,:], att_state)
            ##input shape of cap_lstm2: [batch_size, 2*dim_hidden]
            with tf.variable_scope('cap_lstm'):
                if i > 0:
                    tf.get_variable_scope().reuse_variables()
                    output2, cap_state = cap_lstm(tf.concat([padding, output1], 1), cap_state)
                else:
                    output2, cap_state = cap_lstm(tf.concat([padding, output1], 1), cap_state)
        ## Decoding stage        
        
        for i in range(caption_steps):
            
            with tf.device('/cpu:0'):
                current_word_embed = tf.nn.embedding_lookup(embedding, self.caption[:,i])
            
            with tf.variable_scope('att_lstm'):
                tf.get_variable_scope().reuse_variables()
                output1, att_state = att_lstm(padding, att_state)
                        
            with tf.variable_scope('cap_lstm'):
                tf.get_variable_scope().reuse_variables()
                
            cap_lstm_outputs.append(output2)

        output = tf.reshape(tf.concat(cap_lstm_outputs , 1), [-1, dim_hidden])                
        onehot_word_logits = tf.nn.xw_plus_b(output, w_word_onehot, b_word_onehot)
        
        self.predict_result = tf.reshape(onehot_word_logits, [batch_size, caption_steps, vocab_size] )
        
        loss = tf.contrib.legacy_seq2seq.sequence_loss_by_example([onehot_word_logits],
                                                                  [tf.reshape(self.caption[:,1:], [-1])],
                                                                  [tf.reshape(self.caption_mask[:,1:], [-1])])
        
        self.cost = tf.reduce_mean(loss)
        self.global_step = tf.Variable(0, trainable=False)
        self.train_op = tf.train.AdamOptimizer().minimize(self.cost, global_step=self.global_step)
        
        config = tf.ConfigProto(log_device_placement = True)
        config.gpu_options.allow_growth = True
        
        self.sess = tf.Session(config=config)

    def train(self, input_frame, input_caption,input_caption_mask, keep_prob=0.5):
        _,cost = self.sess.run([self.train_op,self.cost],feed_dict={self.frame:input_frame, 
                                                                    self.caption:input_caption, 
                                                                    self.caption_mask:input_caption_mask,
                                                                    self.train_state:True})
        return cost
    
    def initialize(self):
        self.sess.run(tf.global_variables_initializer())