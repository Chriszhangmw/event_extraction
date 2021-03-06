
import os
import logging
from torch.utils.data import DataLoader
from sklearn.model_selection import KFold
from src_final.preprocess.processor import *
from src_final.utils.trainer import train
from src_final.utils.options import TrainArgs
from src_final.utils.model_utils import build_model
from src_final.utils.dataset_utils import build_dataset
from src_final.utils.evaluator import trigger_evaluation, role1_evaluation, role2_evaluation, attribution_evaluation
from src_final.utils.functions_utils import set_seed, get_model_path_list, load_model_and_parallel, \
    prepare_info, prepare_para_dict



def train_base(opt, info_dict, train_examples, dev_info=None):
    feature_para, dataset_para, model_para = prepare_para_dict(opt, info_dict)

    train_features = convert_examples_to_features(opt.task_type, train_examples, opt.bert_dir,
                                                  opt.max_seq_len, **feature_para)

    train_dataset = build_dataset(opt.task_type, train_features, 'train', **dataset_para)

    model = build_model(opt.task_type, opt.bert_dir, **model_para)

    train(opt, model, train_dataset)

    if dev_info is not None:
        dev_examples, dev_callback_info = dev_info

        dev_features = convert_examples_to_features(opt.task_type, dev_examples, opt.bert_dir,
                                                    opt.max_seq_len, **feature_para)
        dev_dataset = build_dataset(opt.task_type, dev_features, 'dev', **dataset_para)
        dev_loader = DataLoader(dev_dataset, batch_size=opt.eval_batch_size,
                                shuffle=False, num_workers=8)
        dev_info = (dev_loader, dev_callback_info)

        model_path_list = get_model_path_list(opt.output_dir)

        metric_str = ''

        max_f1 = 0.
        max_f1_step = 0

        for idx, model_path in enumerate(model_path_list):

            tmp_step = model_path.split('/')[-2].split('-')[-1]

            model, device = load_model_and_parallel(model, opt.gpu_ids[0],
                                                    ckpt_path=model_path)

            if opt.task_type == 'trigger':

                tmp_metric_str, tmp_f1 = trigger_evaluation(model, dev_info, device,
                                                            start_threshold=opt.start_threshold,
                                                            end_threshold=opt.end_threshold)

            elif opt.task_type == 'role1':
                tmp_metric_str, tmp_f1 = role1_evaluation(model, dev_info, device,
                                                          start_threshold=opt.start_threshold,
                                                          end_threshold=opt.end_threshold)
            elif opt.task_type == 'role2':
                tmp_metric_str, tmp_f1 = role2_evaluation(model, dev_info, device)
            else:
                tmp_metric_str, tmp_f1 = attribution_evaluation(model, dev_info, device,
                                                                polarity2id=info_dict['polarity2id'],
                                                                tense2id=info_dict['tense2id'])

            metric_str += f'In step {tmp_step}: {tmp_metric_str}' + '\n\n'

            if tmp_f1 > max_f1:
                max_f1 = tmp_f1
                max_f1_step = tmp_step

        max_metric_str = f'Max f1 is: {max_f1}, in step {max_f1_step}'

        metric_str += max_metric_str + '\n'

        eval_save_path = os.path.join(opt.output_dir, 'eval_metric.txt')

        with open(eval_save_path, 'a', encoding='utf-8') as f1:
            f1.write(metric_str)


def training(opt):
    processors = {'trigger': TriggerProcessor,
                  'role1': RoleProcessor,
                  'role2': RoleProcessor,
                  'attribution': AttributionProcessor}

    processor = processors[opt.task_type]()

    info_dict = prepare_info(opt.task_type, opt.mid_data_dir)

    train_raw_examples = processor.read_json(os.path.join(opt.raw_data_dir, 'stack.json'))
    train_examples = processor.get_train_examples(train_raw_examples)

    if opt.enhance_data and opt.task_type in ['trigger', 'role1', 'role2']:
        # trigger & role1
        if opt.task_type in ['trigger', 'role1']:
            train_aux_raw_examples = processor.read_json(os.path.join(opt.aux_data_dir, f'{opt.task_type}_first.json'))
            train_examples += processor.get_train_examples(train_aux_raw_examples)

        # sub & obj ?????????????????????????????????
        if opt.task_type == 'role1':
            train_aux_raw_examples = processor.read_json(os.path.join(opt.aux_data_dir, f'{opt.task_type}_second.json'))
            train_examples += processor.get_train_examples(train_aux_raw_examples)
        # time & loc ?????????????????????????????????
        elif opt.task_type == 'role2':
            train_aux_raw_examples = processor.read_json(os.path.join(opt.raw_data_dir, 'preliminary_stack.json'))
            train_examples += processor.get_train_examples(train_aux_raw_examples)
        # trigger ??????????????????????????????????????????
        else:

            train_aux_raw_examples = processor.read_json(os.path.join(opt.aux_data_dir,
                                                                      f'{opt.task_type}_third_new.json'))
            train_examples += processor.get_train_examples(train_aux_raw_examples)

    dev_info = None
    if opt.eval_model:
        dev_raw_examples = processor.read_json(os.path.join(opt.raw_data_dir, 'dev.json'))
        dev_info = processor.get_dev_examples(dev_raw_examples)

    train_base(opt, info_dict, train_examples, dev_info)




if __name__ == '__main__':
    args = TrainArgs().get_parser()

    assert args.mode in ['train'], 'mode mismatch'
    assert args.task_type in ['trigger', 'role1', 'role2', 'attribution'], 'task mismatch'

    mode =  'final'
    args.output_dir = os.path.join(args.output_dir, mode, args.task_type, args.bert_type)

    set_seed(seed=123)

    if args.task_type == 'trigger':
        if args.use_distant_trigger:
            args.output_dir += '_distant_trigger'
    elif args.task_type in ['role1', 'role2']:
        if args.use_trigger_distance:
            args.output_dir += '_distance'

    if args.attack_train != '':
        args.output_dir += f'_{args.attack_train}'

    if args.weight_decay:
        args.output_dir += '_wd'

    if args.enhance_data and args.task_type in ['trigger', 'role1', 'role2']:
        args.output_dir += '_enhanced'

    if not os.path.exists(args.output_dir):
        os.makedirs(args.output_dir, exist_ok=True)


    training(args)
