from __future__ import absolute_import
from __future__ import division
from __future__ import print_function

import collections
import math
import os
import random
import sys
import zipfile

from six.moves import urllib
from six.moves import xrange

import numpy as np
from cntk.initializer import uniform
from cntk.learner import learning_rate_schedule, sgd, UnitType
from cntk.ops import *
from cntk.trainer import Trainer
from cntk.utils import ProgressPrinter


curr_epoch = 0
emb_size = 256
minibatch_size = 512
num_epochs = 1
skip_window = 1
vocab_size = 10000
words_per_epoch = 10000
words_seen = 0


data = list()
id2word = list()
vocab_count = list()


def lrmodel(inp, out_dim):
    inp_dim = inp.shape[0]
    wt = parameter(shape=(inp_dim, out_dim), init=uniform(scale=1.0))
    b = parameter(shape=(out_dim), init=uniform(scale=1.0))
    out = times(inp, wt) + b
    return out


def train(emb_size, vocab_size, batch_size, vocab_count):
    inp = input_variable(shape=(vocab_size,))
    label = input_variable(shape=(vocab_size,))

    init_width = 0.5 / emb_size
    emb = parameter(shape=(vocab_size, emb_size), init=uniform(scale=init_width))
    embinp = times(inp, emb)
    
    z = lrmodel(embinp, vocab_size)        # logistic regression model
    loss = cross_entropy_with_softmax(z, label)
    normloss = element_divide(loss, constant(value=batch_size))

    eval_error = classification_error(z, label)
    lr_per_minibatch = learning_rate_schedule([0.005], UnitType.minibatch)
    learner = sgd(z.parameters, lr=lr_per_minibatch)
    trainer = Trainer(z, normloss, eval_error, learner)

    return inp, label, trainer


def maybe_download(filename, expected_bytes):
    """Download a file if not present, and make sure it's the right size."""
    url = 'http://mattmahoney.net/dc/'
    if not os.path.exists(filename):
        print('Downloading Sample Data..')
        filename, _ = urllib.request.urlretrieve(url + filename, filename)
    statinfo = os.stat(filename)
    if statinfo.st_size == expected_bytes:
        print('Found and verified', filename)
    else:
        print(statinfo.st_size)
        raise Exception('Failed to verify ' + filename + '. Can you get to it with a browser?')
    return filename


def read_data(filename):
    """Read the file as a list of words"""
    data = list()
    with codecs.open(filename, 'r', 'utf-8') as f:
        for line in f:
            data += line.split()
    return data


def read_data_zip(filename):
    """Extract the first file enclosed in a zip file as a list of words"""
    with zipfile.ZipFile(filename) as f:
        bdata = f.read(f.namelist()[0]).split()
    data = [x.decode() for x in bdata]
    return data


def build_dataset(words):
    global data, vocab_size, vocab_count, words_per_epoch, id2word
    count = [['UNK', -1]]
    count.extend(collections.Counter(words).most_common(vocab_size - 1))
    # print(len(count))
    # print(count[-1])
    dictionary = dict()
    id2word = list()
    for word, _ in count:
        dictionary[word] = len(dictionary)
        id2word.append(word)
    # print(dictionary)
    data = list()
    unk_count = 0
    for word in words:
        if word in dictionary:
            index = dictionary[word]
        else:
            index = 0  # dictionary['UNK']
            unk_count += 1
        data.append(index)
    count[0][1] = unk_count
    reverse_dictionary = dict(zip(dictionary.values(), dictionary.keys()))
    vocab_count = list()
    for elem in sorted(reverse_dictionary.items()):
        vocab_count.append(count[elem[0]][1])
    words_per_epoch = len(data)


# Helper function to generate a random data sample
def generate_random_data_sample(sample_size, feature_dim, num_classes):
    # Create synthetic data using NumPy.
    Y = np.random.randint(size=(sample_size, 1), low=0, high=num_classes)

    # Make sure that the data is separable
    X = (np.random.randn(sample_size, feature_dim)+3) * (Y+1)
    X = X.reshape(sample_size, 1, -1)

    # converting class 0 into the vector "1 0 0",
    # class 1 into vector "0 1 0", ...
    class_ind = [Y==class_number for class_number in range(num_classes)]
    Y = np.asarray(np.hstack(class_ind),dtype=np.float32)
    Y = Y.reshape(sample_size, 1, -1)
    return X, Y


def generate_batch(batch_size, skip_window):
    """ Function to generate a training batch for the skip-gram model. """
    global data, curr_epoch, words_per_epoch, words_seen
    data_index = words_seen - curr_epoch * words_per_epoch
    num_skips = 2 * skip_window
    batch = np.ndarray(shape=(batch_size, 1), dtype=np.int32)
    labels = np.ndarray(shape=(batch_size, 1), dtype=np.int32)
    span = 2 * skip_window + 1 # [ skip_window target skip_window ]
    buffer = collections.deque(maxlen=span)
    for _ in range(span):
        buffer.append(data[data_index])
        words_seen += 1
        data_index += 1
        if data_index >= len(data):
            curr_epoch += 1
            data_index -= len(data)
    for i in range(batch_size // num_skips):
        target = skip_window    # target label at the center of the buffer
        targets_to_avoid = [ skip_window ]
        for j in range(num_skips):
            while target in targets_to_avoid:
                target = random.randint(0, span - 1)
            targets_to_avoid.append(target)
            batch[i * num_skips + j, 0] = buffer[skip_window]
            labels[i * num_skips + j, 0] = buffer[target]
        buffer.append(data[data_index])
        words_seen += 1
        data_index += 1
        if data_index >= len(data):
            curr_epoch += 1
            data_index -= len(data)
    return batch, labels


def process_text(filename):
    if filename == 'runexample':
        filename = maybe_download('text8.zip', 31344016)
        words = read_data_zip(filename)
    else:
        words = read_data(filename)
    build_dataset(words)


def get_one_hot(origlabels):
    labels = np.zeros(shape=(minibatch_size, vocab_size), dtype=np.float32)
    for t in xrange(len(origlabels)):
        if origlabels[t, 0] < vocab_size and origlabels[t, 0] >= 0:
            labels[t, origlabels[t, 0]] = 1.0
    return labels


def main():
    # Ensure we always get the same amount of randomness
    np.random.seed(0)

    global minibatch_size, skip_window

    if len(sys.argv) < 2:
        print('Insufficient number of arguments')
        exit(1)
    filename = sys.argv[1]
    process_text(filename)

    inp, label, trainer = train(emb_size, vocab_size, minibatch_size, vocab_count)
    pp = ProgressPrinter(128)
    for _epoch in range(num_epochs):
        for i in range(200):
            features, labels = generate_batch(minibatch_size, skip_window)
            features = get_one_hot(features)
            labels = get_one_hot(labels)
            # features, labels = generate_random_data_sample(minibatch_size, vocab_size, vocab_size)

            trainer.train_minibatch({inp: features, label: labels})
            pp.update_with_trainer(trainer)
            print(i, ' training...')
        pp.epoch_summary()

    test_features, test_labels = generate_batch(minibatch_size, skip_window)
    test_features = get_one_hot(test_features)
    test_labels = get_one_hot(test_labels)
    
    avg_error = trainer.test_minibatch({inp: test_features, label: test_labels})
    print('Avg. Error on Test Set: ', avg_error)


if __name__ == '__main__':
    main()
