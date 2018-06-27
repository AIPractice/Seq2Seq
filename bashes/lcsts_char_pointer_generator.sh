#!/usr/bin/env bash
cd ..
python3 train.py\
    --model_class pointer_generator\
    --batch_size 256\
    --hidden_units 400\
    --embedding_size 300\
    --attention_units 250\
    --encoder_depth 3\
    --decoder_depth 3\
    --encoder_max_time_steps 140\
    --decoder_max_time_steps 30\
    --display_freq 5\
    --save_freq 2000\
    --valid_freq 400\
    --model_dir checkpoints/lcsts_char_pointer_generator\
    --model_name lcsts.ckpt\
    --source_vocabulary dataset/lcsts/char/vocabs.json\
    --target_vocabulary dataset/lcsts/char/vocabs.json\
    --source_train_data dataset/lcsts/char/sources.train.txt\
    --target_train_data dataset/lcsts/char/summaries.train.txt\
    --source_valid_data dataset/lcsts/char/sources.eval.txt\
    --target_valid_data dataset/lcsts/char/summaries.eval.txt\
    --encoder_vocab_size 10606\
    --decoder_vocab_size 10606\
    --cell_type gru\
    --max_epochs 100000