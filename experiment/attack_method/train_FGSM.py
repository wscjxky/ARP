import tensorflow as tf
import tensorflow.contrib.slim as slim
import tensorflow.contrib.slim.nets as nets
from urllib.request import urlretrieve
import json
import matplotlib.pyplot as plt
import PIL
import numpy as np
step=16
result_file=str(step)+'_FGSM_attack.txt'
import  os

os.environ["CUDA_VISIBLE_DEVICES"]='3'

config = tf.ConfigProto()
config.gpu_options.allow_growth = True
sess = tf.InteractiveSession(config=config)
y_hat = tf.placeholder(tf.int64, ())
labels = tf.one_hot(y_hat, 1000)

x = tf.placeholder(tf.float32, (1, 299, 299, 3))
x_rar = tf.placeholder(tf.float32, (1, 299, 299, 3))
x_adv = tf.Variable(tf.zeros([1, 299, 299, 3]))

_POOL_NAME = 'Mixed_7c'
_POOL_SIZE = 8
_MODEL_END = 'Logits'


def inception(image, reuse):
    preprocessed = tf.multiply(tf.subtract(image, 0.5), 2.0)
    arg_scope = nets.inception.inception_v3_arg_scope(weight_decay=0.0)
    with slim.arg_scope(arg_scope):
        logits, end_point = nets.inception.inception_v3(preprocessed, 1001, is_training=False, reuse=reuse)
        logits = logits[:, 1:]  # ignore background class
        probs = tf.nn.softmax(logits)  # probabilities
    return logits, probs, end_point


def grad_cam(end_point, pre_calss_one_hot):
    conv_layer = end_point[_POOL_NAME]
    signal = tf.multiply(end_point[_MODEL_END][:, 1:], pre_calss_one_hot)
    loss = tf.reduce_mean(signal, 1)
    grads = tf.gradients(loss, conv_layer)[0]
    norm_grads = tf.div(grads, tf.sqrt(tf.reduce_mean(tf.square(grads))) + tf.constant(1e-5))
    weights = tf.reduce_mean(norm_grads, axis=(1, 2))
    weights = tf.expand_dims(weights, 1)
    weights = tf.expand_dims(weights, 1)
    weights = tf.tile(weights, [1, _POOL_SIZE, _POOL_SIZE, 1])
    pre_cam = tf.multiply(weights, conv_layer)
    cam = tf.reduce_sum(pre_cam, 3)
    cam = tf.expand_dims(cam, 3)
    cam = tf.nn.relu(cam)
    resize_cam = tf.image.resize_images(cam, [299, 299])
    resize_cam = resize_cam / tf.reduce_max(resize_cam)
    return resize_cam


def cal_IOU(rar_map, adv_map):
    clip_rar = tf.sign(tf.nn.relu(rar_map - tf.reduce_max(rar_map) * 0.5))
    clip_adv = tf.sign(tf.nn.relu(adv_map - tf.reduce_max(rar_map) * 0.5))

    tt_tmp = clip_rar + clip_adv
    total_clip = tf.sign(tt_tmp)

    b_tmp = tf.nn.relu(clip_rar + clip_adv - 1)
    bing_clip = tf.sign(b_tmp)

    iou = tf.reduce_sum(bing_clip, [1, 2, 3]) / tf.reduce_sum(total_clip, [1, 2, 3])
    return iou


def g_loss(rar_map, adv_map):
    grad_cam_loss = tf.reduce_sum(tf.pow(rar_map - adv_map, 2))
    return grad_cam_loss


def sign_gloss(rar_map, adv_map):
    clip_rar = tf.sign(tf.nn.relu(rar_map - tf.reduce_max(rar_map) * 0.2))
    clip_rar = tf.reshape(clip_rar, [-1, 299 * 299])
    flatten_rar_amp = tf.reshape(rar_map, [-1, 299 * 299])
    flatten_adv_map = tf.reshape(adv_map, [-1, 299 * 299])

    gloss = tf.reduce_mean(tf.abs(clip_rar - flatten_adv_map))

    # closs
    ARGMAX = tf.argmax(probs, 1)
    MA = tf.one_hot(ARGMAX, 1000)
    closs = -tf.losses.softmax_cross_entropy(MA, adv_logits)
    return closs
    # return - 10 * gloss


logits, probs, end_point = inception(x, reuse=tf.AUTO_REUSE)
rar_logits, rar_probs, rar_end_point = inception(x_rar, reuse=tf.AUTO_REUSE)
adv_logits, adv_probs, adv_end_point = inception(x_adv, reuse=tf.AUTO_REUSE)
_correct = tf.equal(tf.argmax(rar_probs, 1), (tf.argmax(adv_probs, 1)))
restore_vars = [
    var for var in tf.global_variables()
    if var.name.startswith('InceptionV3/')
]
saver = tf.train.Saver(restore_vars)
saver.restore(sess, "../model/inception_v3.ckpt")

imagenet_json=('../dataset/imagenet.json')
with open(imagenet_json) as f:
    imagenet_labels = json.load(f)


def classify(img, correct_class=None, target_class=None):
    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(10, 8))
    fig.sca(ax1)
    p = sess.run(rar_probs, feed_dict={x_rar: img})[0]
    ax1.imshow(img)
    fig.sca(ax1)

    topk = list(p.argsort()[-10:][::-1])
    topprobs = p[topk]
    barlist = ax2.bar(range(10), topprobs)
    if target_class in topk:
        barlist[topk.index(target_class)].set_color('r')
    if correct_class in topk:
        barlist[topk.index(correct_class)].set_color('g')
    plt.sca(ax2)
    plt.ylim([0, 1.1])
    plt.xticks(range(10),
               [imagenet_labels[i][:15] for i in topk],
               rotation='vertical')
    fig.subplots_adjust(bottom=0.2)
    plt.show()


def load(img_path):
    img = PIL.Image.open(img_path).convert('RGB')
    big_dim = max(img.width, img.height)
    wide = img.width > img.height
    new_w = 299 if not wide else int(img.width * 299 / img.height)
    new_h = 299 if wide else int(img.height * 299 / img.width)
    img = img.resize((new_w, new_h)).crop((0, 0, 299, 299))
    img = (np.asarray(img) / 255.0).astype(np.float32)
    return img


rar_grad_cam = grad_cam(rar_end_point, labels)
adv_grad_cam = grad_cam(adv_end_point, labels)

get_random = tf.sign(tf.random_normal([299, 299, 3])) * 8 / 255

get_iou_op = cal_IOU(rar_grad_cam, adv_grad_cam)
gloss = g_loss(rar_grad_cam, adv_grad_cam)

assign_op = tf.assign(x_adv, x)

# 自动更新
get_sign_gloss = sign_gloss(rar_grad_cam, adv_grad_cam)
train_op = tf.train.GradientDescentOptimizer(1.2).minimize(get_sign_gloss, var_list=[x_adv])
# 手动更新
grad_sgloss = tf.gradients(get_sign_gloss, x_adv)[0]
g_assign = tf.assign(x_adv, x_adv - tf.sign(grad_sgloss) * step / 255)
# project
epsilon = 4 / 255
below = x - epsilon
above = x + epsilon
projected = tf.clip_by_value(tf.clip_by_value(x_adv, below, above), 0, 1)
with tf.control_dependencies([projected]):
    project_step = tf.assign(x_adv, projected)

correct = tf.equal(tf.argmax(rar_probs, 1), (tf.argmax(adv_probs, 1)))
_corrects=tf.equal(tf.argmax(rar_probs, 1), y_hat)
sess.graph.finalize()

import cv2


def get_hot_map(RGC, rar_img):
    RGC = np.reshape(RGC / np.max(RGC), [299, 299])
    RGC = np.expand_dims(RGC, 2)
    RGC = np.tile(RGC, [1, 1, 3])
    RGC = cv2.applyColorMap(np.uint8(255 * RGC), cv2.COLORMAP_JET)
    RGC = cv2.cvtColor(RGC, cv2.COLOR_BGR2RGB)
    alpha = 0.0072
    rar_img /= rar_img.max()
    rar = alpha * RGC + rar_img
    rar /= rar.max()
    return rar


# Begin Run
import os
labels_file = '../dataset/imagenet_labels.txt'

imgs_path = "../dataset/img_val/"
attack_count = 0
defense_count = 0
count=0
if os.path.exists(result_file):
    os.remove(result_file)
with open(labels_file, 'r', encoding='utf-8')as f:
    lines = f.readlines()
    for index, line in enumerate(lines):
        imgs = []
        labels = []
        label_letter = line.split(' ')
        ground_truths = []
        label_letter = label_letter[0]
        img_class = index
        dir_name = imgs_path + str(label_letter)
        for root, dirs, files in os.walk(dir_name):
            for file in files:
                img_path = dir_name + '/' + file
                label_path = '../dataset/val/' + str(file)[:-4] + 'xml'
                img=load(img_path)
                sess.run(assign_op, feed_dict={x: [img]})
                rar_img = img
                corrects=sess.run(_corrects, feed_dict={x: [img], x_rar: [rar_img], y_hat: img_class})
                if corrects[0]:
                    for i in range(3):
                        adv_map = sess.run(adv_grad_cam, feed_dict={y_hat: img_class})
                        adv_img = np.reshape(sess.run(x_adv), [299, 299, 3])
                        adv_map = get_hot_map(adv_map, adv_img)
                        sess.run(train_op, feed_dict={x: [img], x_rar: [rar_img], y_hat: img_class})
                        # sess.run(project_step, feed_dict={x: [rar_img]})
                    result=sess.run(correct, feed_dict={x: [img], x_rar: [rar_img], y_hat: img_class})
                    if result[0]:
                        defense_count+=1
                    else:
                        attack_count+=1
                    count+=1
                    print(attack_count,defense_count,count)
                    with open(result_file, 'a') as f_w:
                        f_w.write(str(result[0])+"\n")
                else:
                    print('failed')
        with open(result_file, 'a') as f_w:
            f_w.write(str(attack_count)+str(defense_count)+str(count))
