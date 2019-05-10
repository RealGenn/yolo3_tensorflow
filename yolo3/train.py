import tensorflow as tf
import numpy as np
import cv2
import time

from tensorflow.python import debug as tf_debug

from net.yolo3_net import model, loss
from util.box_util import xy2wh_np, wh2xy_np, box_anchor_iou, np_sigmoid
from util.image_util import read_image_and_lable


class YOLO():
    def __init__(self):
        self.anchor_path = "C:\\Users\\qiguodong\\PycharmProjects\\egame_qq_wzry\\yolo3\\model_data\\yolo_anchors.txt"
        self.train_path = 'C:\\Users\\qiguodong\\PycharmProjects\\egame_qq_wzry\\yolo3\\model_data\\train.txt'
        self.classes_path = 'C:\\Users\\qiguodong\\PycharmProjects\\egame_qq_wzry\\yolo3\\model_data\\voc_classes.txt'
        self.log_path = 'C:\\Users\\qiguodong\\PycharmProjects\\egame_qq_wzry\\yolo3\\logs\\'
        self.pretrain_path = self.log_path
        # self.pretrain_path = ''

        self.batch_size = 4

        self.learn_rate = 1e-4
        self.lambda_coord = 1
        self.lambda_noobj = 0.5
        self.iou_threshold = 0.2

        self.classes = self._get_classes()
        self.anchors = self._get_anchors()
        self.hw = [320, 640]

        self.input = tf.placeholder(tf.float32, [self.batch_size] + self.hw + [3])

        self.label = None

        with open(self.train_path) as f:
            self.gts = f.readlines()

    def _get_anchors(self):
        """loads the anchors from a file"""
        with open(self.anchor_path) as f:
            anchors = f.readline()
        anchors = [float(x) for x in anchors.split(',')]
        return np.array(anchors).reshape(-1, 2)

    def _get_classes(self):
        """loads the classes"""
        with open(self.classes_path) as f:
            class_names = f.readlines()
        class_names = [c.strip() for c in class_names]
        return class_names

    def generate_data(self, gts, grid_shape):
        img_files = []
        labels = []
        for idx in range(len(gts)):
            res = read_image_and_lable(gts[idx], self.hw, self.anchors)
            kk = 0
            while not res:
                res = read_image_and_lable(gts[kk], self.hw, self.anchors)
                kk += 1
            img, _label, _ = res

            img_files.append(img)
            _label_ = np.concatenate([xy2wh_np(_label[:, :4]), _label[:, 4:]], -1)  # change to xywh

            gds = []
            for g_id, g_shape in enumerate(grid_shape):
                anchors = self.anchors[[g_id, g_id + 1, g_id + 2]]
                gd = np.zeros(g_shape[1:3] + [3, 5 + len(self.classes)])
                h_r = self.hw[0] / gd.shape[0]
                w_r = self.hw[1] / gd.shape[1]
                for per_label in _label_:
                    x0, y0, w, h = per_label[:4]
                    if w == 0 or h == 0:
                        continue
                    i = int(np.floor(x0 / w_r))
                    j = int(np.floor(y0 / h_r))
                    box_iou = box_anchor_iou(anchors, per_label[2:4])
                    k = np.argmax(box_iou)
                    # gd[j, i, k, 0] = x0 / w_r - i
                    # gd[j, i, k, 1] = y0 / h_r - j
                    gd[j, i, k, 0] = x0
                    gd[j, i, k, 1] = y0
                    # gd[j, i, k, 2] = np.log(w / anchors[k, 0] + 1e-15)
                    # gd[j, i, k, 3] = np.log(h / anchors[k, 1] + 1e-15)
                    gd[j, i, k, 2] = w
                    gd[j, i, k, 3] = h
                    gd[j, i, k, 4] = 1
                    gd[j, i, k, 4 + int(per_label[4])] = 1

                gds.append(gd.reshape([-1, 3, 5 + len(self.classes)]))
            labels.append(np.concatenate(gds, 0))

        img_files, labels = np.array(img_files, np.float32), np.array(labels, np.float32)
        return img_files, labels

    def train(self):
        # pred, losses, op = self.create_model()
        pred = model(self.input, len(self.classes), self.anchors, True, 0.3)
        grid_shape = [g.get_shape().as_list() for g in pred[1]]

        s = sum([g[2] * g[1] for g in grid_shape])
        self.label = tf.placeholder(tf.float32, [self.batch_size, s, 3, 5 + len(self.classes)])

        losses = loss(pred, self.label, self.anchors, self.hw, self.lambda_coord, self.lambda_noobj,
                      self.iou_threshold)
        opt = tf.train.AdamOptimizer(self.learn_rate)
        op = opt.minimize(losses)

        # img, label = self.generate_data(self.gts[0:0 + self.batch_size], grid_shape)

        # summary
        writer = tf.summary.FileWriter(self.log_path)
        img_tensor = tf.placeholder(tf.float32, [self.batch_size] + self.hw + [3])
        loss_tensor = tf.placeholder(tf.float32)
        tf.summary.scalar('losses', loss_tensor)
        tf.summary.image('img', img_tensor, self.batch_size)
        summary = tf.summary.merge_all()

        config = tf.ConfigProto(gpu_options=tf.GPUOptions(allow_growth=True))
        sess = tf.Session(config=config)
        # sess = tf_debug.LocalCLIDebugWrapperSession(sess)
        # sess = tf_debug.TensorBoardDebugWrapperSession(sess, "PC-DAIXILI:6001")
        saver = tf.train.Saver()
        if not len(self.pretrain_path):
            init = tf.global_variables_initializer()
            sess.run(init)
        else:
            saver.restore(sess, tf.train.latest_checkpoint(self.pretrain_path))

        i = 0
        for step in range(100000):
            if i + self.batch_size >= len(self.gts):
                i = 0
                np.random.shuffle(self.gts)
            img, label = self.generate_data(self.gts[i:i + self.batch_size], grid_shape)
            pred_, losses_, _ = sess.run([pred, losses, op], {
                self.input: img,
                self.label: label
            })
            i += self.batch_size
            print('step:{} loss:{}'.format(step, losses_))

            if (step + 1) % 10 == 1:  # for visible
                boxes, grid = pred_
                score = np_sigmoid(boxes[..., 4:5]) * np_sigmoid(boxes[..., 5:])
                vis_img = []

                for b in range(self.batch_size):
                    idx = np.where(score[b] > 0.2)
                    box_select = boxes[b][idx[:2]]
                    box_xywh = box_select[:, :4]
                    box_xyxy = wh2xy_np(box_xywh)
                    box_socre = score[b][idx]
                    clsid = idx[2]

                    per_img = (img[b] + 1) * 128
                    for bbox in box_xyxy:
                        per_img = cv2.rectangle(per_img, tuple(np.int32([bbox[0], bbox[1]])),
                                                tuple(np.int32([bbox[2], bbox[3]])), (0, 255, 0), 2)
                    vis_img.append(per_img)
                ss = sess.run(summary, feed_dict={
                    img_tensor: np.array(vis_img),
                    loss_tensor: losses_
                })
                writer.add_summary(ss, step)
            if (step + 1) % 100 == 0:
                saver.save(sess,
                           'C:\\Users\\qiguodong\\PycharmProjects\\egame_qq_wzry\\yolo3\\logs\\step{}_loss{:.4f}'.format(
                               step + 1, losses_))


if __name__ == '__main__':
    YOLO().train()
