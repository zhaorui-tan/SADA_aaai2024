import os, sys
import os.path as osp
import time
import random
import argparse
import numpy as np
from PIL import Image
import pprint
from tqdm import tqdm

import torch
import torch.backends.cudnn as cudnn
from torchvision.utils import save_image, make_grid
import torchvision.utils as vutils
import multiprocessing as mp
if sys.version_info[0] == 2:
    import cPickle as pickle
else:
    import pickle

ROOT_PATH = osp.abspath(osp.join(osp.dirname(osp.abspath(__file__)),  ".."))
sys.path.insert(0, ROOT_PATH)
from lib.utils import mkdir_p, get_rank, merge_args_yaml, get_time_stamp, load_netG
from lib.utils import tokenize, truncated_noise, prepare_sample_data
from lib.perpare import prepare_models


def parse_args():
    # Training settings
    parser = argparse.ArgumentParser(description='DF-GAN')
    parser.add_argument('--cfg', dest='cfg_file', type=str, default='../cfg/model/bird_review.yml',
                        help='optional config file')
    parser.add_argument('--imgs_per_sent', type=int, default=1,
                        help='the number of images per sentence')
    parser.add_argument('--imsize', type=int, default=256,
                        help='image size')
    parser.add_argument('--cuda', type=bool, default=False,
                        help='if use GPU')
    parser.add_argument('--train', type=bool, default=False,
                        help='if training')
    parser.add_argument('--multi_gpus', type=bool, default=False,
                        help='if use multi-gpu')
    parser.add_argument('--gpu_id', type=int, default=2,
                        help='gpu id')
    parser.add_argument('--local_rank', default=-1, type=int,
        help='node rank for distributed training')
    parser.add_argument('--random_sample', action='store_true',default=True, 
        help='whether to sample the dataset with random sampler')
    args = parser.parse_args()
    return args


def build_word_dict(pickle_path):
    with open(pickle_path, 'rb') as f:
        x = pickle.load(f)
        wordtoix = x[3]
        del x
        n_words = len(wordtoix)
        print('Load from: ', pickle_path)
    return n_words, wordtoix


def sample_example(wordtoix, netG, aug, text_encoder, args, n1):
    batch_size, device = args.imgs_per_sent, args.device
    text_filepath, img_save_path = args.example_captions, args.samples_save_dir
    truncation, trunc_rate = args.truncation, args.trunc_rate
    z_dim = args.z_dim
    captions, cap_lens, _ = tokenize(wordtoix, text_filepath)
    sent_embs, _ = prepare_sample_data(captions, cap_lens, text_encoder, device)
    caption_num = sent_embs.size(0)
    # get noise
    if truncation==True:
        seed = random.randint(1,10000)
        # seed = None
        noise = truncated_noise(batch_size, z_dim, trunc_rate, seed)
        noise = torch.tensor(noise, dtype=torch.float).to(device)

    else:
        noise = torch.randn(batch_size, z_dim).to(device)


    # sampling
    with torch.no_grad():
        fakes = []
        for i in tqdm(range(caption_num)):
            sent_emb = sent_embs[i].unsqueeze(0).repeat(batch_size, 1)

            fakes = netG(noise, sent_emb)
            img_name = osp.join(img_save_path,'Sent%03d.png'%(i+1))
            vutils.save_image(fakes.data, img_name, nrow=1, range=(-1, 1), normalize=True)

            # c_noise = ((torch.rand(batch_size, 256) - 0.5) * 2).to(device)
            sent_emb_aug = aug(n1, sent_emb)

            fake_aug = netG(noise, sent_emb_aug)
            img_name = osp.join(img_save_path, 'Sent%03d_aug100.png' % (i + 1))
            vutils.save_image(fake_aug.data, img_name, nrow=1, range=(-1, 1), normalize=True)

            sent_emb_aug_2 = sent_emb + (sent_emb_aug - sent_emb)*0.75
            fake_aug = netG(noise, sent_emb_aug_2)
            img_name = osp.join(img_save_path, 'Sent%03d_aug075.png' % (i + 1))
            vutils.save_image(fake_aug.data, img_name, nrow=1, range=(-1, 1), normalize=True)

            sent_emb_aug_3 = sent_emb + (sent_emb_aug - sent_emb)*0.5
            fake_aug = netG(noise, sent_emb_aug_3)
            img_name = osp.join(img_save_path, 'Sent%03d_aug050.png' % (i + 1))
            vutils.save_image(fake_aug.data, img_name, nrow=1, range=(-1, 1), normalize=True)
            torch.cuda.empty_cache()

            sent_emb_aug_3 = sent_emb + (sent_emb_aug - sent_emb) * 0.25
            fake_aug = netG(noise, sent_emb_aug_3)
            img_name = osp.join(img_save_path, 'Sent%03d_aug025.png' % (i + 1))
            vutils.save_image(fake_aug.data, img_name, nrow=1, range=(-1, 1), normalize=True)
            torch.cuda.empty_cache()


def main(args):
    time_stamp = get_time_stamp()
    args.samples_save_dir = osp.join(args.samples_save_dir, time_stamp)

    pickle_path = os.path.join(args.data_dir, 'captions_DAMSM.pickle')
    args.vocab_size, wordtoix = build_word_dict(pickle_path)
    # prepare models
    _, text_encoder, netG, _, _ , aug= prepare_models(args)
    # model_path = osp.join(ROOT_PATH, args.checkpoint)
    if 'coco' in args.dataset_name:
        visual_model_path = './final_models/coco'
    else:
        visual_model_path = './final_models/birds_1300e'

    model_paths = [m for m in os.listdir(visual_model_path) if 'pth' in m]
    print(model_paths)
    for m in model_paths:
        current_model_path = f'{visual_model_path}/{m}'
        args.samples_save_dir = current_model_path[:-4]+'_random'
        print(args.samples_save_dir)
        print('='*100)
        if (args.multi_gpus==True) and (get_rank() != 0):
            None
        else:
            mkdir_p(args.samples_save_dir)

        netG, aug = load_netG(netG, aug, current_model_path, args.multi_gpus, train=False)

        from models.semantic_aug import SemanticAugCal
        if args.dataset_name == 'coco':
            p = 0.01
            aug = SemanticAugCal(args.AUG.DIR, args.AUG.EMBEDDING_DIM,p).cuda()
        else:
            p = 0.2
            aug = SemanticAugCal(args.AUG.DIR, args.AUG.EMBEDDING_DIM,p).cuda()
        print(f'using ITAC,{p}')

        netG.eval()
        aug.eval()

        if (args.multi_gpus==True) and (get_rank() != 0):
            None
        else:
            print('Load %s for NetG'%(args.checkpoint))
            print("************ Start sampling ************")
        start_t = time.time()
        n1 = ((torch.randint(0, 2, (1, args.AUG.EMBEDDING_DIM)) - 0.5) * 2).to('cuda')

        n1 = n1.repeat(args.imgs_per_sent,1)
        sample_example(wordtoix, netG, aug, text_encoder, args, n1)
        end_t = time.time()
        if (args.multi_gpus==True) and (get_rank() != 0):
            None
        else:
            print('*'*40)
            print('Sampling done, %.2fs cost, saved to %s'%(end_t-start_t, args.samples_save_dir))
            print('*'*40)


if __name__ == "__main__":
    args = merge_args_yaml(parse_args())
    # set seed
    if args.manual_seed is None:
        args.manual_seed = 100
    random.seed(args.manual_seed)
    np.random.seed(args.manual_seed)
    torch.manual_seed(args.manual_seed)
    if args.cuda:
        if args.multi_gpus:
            torch.cuda.manual_seed_all(args.manual_seed)
            torch.distributed.init_process_group(backend="nccl")
            local_rank = torch.distributed.get_rank()
            torch.cuda.set_device(local_rank)
            args.device = torch.device("cuda", local_rank)
            args.local_rank = local_rank
        else:
            torch.cuda.manual_seed_all(args.manual_seed)
            torch.cuda.set_device(args.gpu_id)
            args.device = torch.device("cuda")
    else:
        args.device = torch.device('cpu')
    main(args)
