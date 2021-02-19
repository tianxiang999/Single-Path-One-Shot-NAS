import os
import time
import torch
import utils
import config
import torchvision
import torch.nn as nn
from thop import profile
from torchvision import datasets
from utils import data_transforms
from model import SinglePath_OneShot, train, validate, select_top_arch
from torchsummary import summary
from numpy.core.fromnumeric import size

def main():
    # args & device
    args = config.get_args()
    if torch.cuda.is_available():
        print('Train on GPU!')
        device = torch.device("cuda")
    else:
        device = torch.device("cpu")

    # dataset
    assert args.dataset in ['cifar10', 'imagenet']
    train_transform, valid_transform = data_transforms(args)
    if args.dataset == 'cifar10':
        trainset = torchvision.datasets.CIFAR10(root=os.path.join(args.data_dir, 'cifar'), train=True,
                                                download=True, transform=train_transform)
        train_loader = torch.utils.data.DataLoader(trainset, batch_size=args.batch_size,
                                                   shuffle=True, pin_memory=True, num_workers=8)
        valset = torchvision.datasets.CIFAR10(root=os.path.join(args.data_dir, 'cifar'), train=False,
                                              download=True, transform=valid_transform)
        val_loader = torch.utils.data.DataLoader(valset, batch_size=args.batch_size,
                                                 shuffle=False, pin_memory=True, num_workers=8)
    elif args.dataset == 'imagenet':
        train_data_set = datasets.ImageNet(os.path.join(args.data_dir, 'ILSVRC2012', 'train'), train_transform)
        val_data_set = datasets.ImageNet(os.path.join(args.data_dir, 'ILSVRC2012', 'valid'), valid_transform)
        train_loader = torch.utils.data.DataLoader(train_data_set, batch_size=args.batch_size, shuffle=True,
                                                   num_workers=8, pin_memory=True, sampler=None)
        val_loader = torch.utils.data.DataLoader(val_data_set, batch_size=args.batch_size, shuffle=False,
                                                 num_workers=8, pin_memory=True)

    # SinglePath_OneShot
    model = SinglePath_OneShot(args.dataset, args.resize, args.classes, args.layers)
    criterion = nn.CrossEntropyLoss().to(device)
    optimizer = torch.optim.SGD(model.parameters(), args.learning_rate, args.momentum, args.weight_decay)
    scheduler = torch.optim.lr_scheduler.LambdaLR(optimizer, lambda epoch: 1 - (epoch / args.epochs))

    # flops & params & structure
    flops, params = profile(model, inputs=(torch.randn(1, 3, 32, 32),) if args.dataset == 'cifar10'
                            else (torch.randn(1, 3, 224, 224),), verbose=False)
    # print(model)
    print('Random Path of the Supernet: Params: %.2fM, Flops:%.2fM' % ((params / 1e6), (flops / 1e6)))
    model = model.to(device)
    summary(model, (3, 32, 32) if args.dataset == 'cifar10' else (3, 224, 224))

    # train supernet
    start = time.time()

    # weight shocking test
    warmup_batches = 2
    print ("tianxiang: start warmup batch")
    for epoch in range(warmup_batches):
        train(args, epoch, train_loader, device, model, criterion, optimizer, scheduler, supernet=True)
        scheduler.step()

    print ("tianxiang: select top arch:")
    # contain top 3 best arch
    _, top_list = select_top_arch(args, epoch, val_loader, device, model, criterion, supernet=True)
    # print(list_size)
    for t in range(3):
        print("top",t,"list: ",top_list[t])
    
    print ("tianxiang: start train and trace")
    # for each train epoch, train and test every top arch's val acc
    for epoch in range(args.epochs):
        train(args, epoch, train_loader, device, model, criterion, optimizer, scheduler, supernet=True)

        for top in range(3):
            val = validate(args, epoch, val_loader, device, model, criterion, supernet=True,choice=top_list[top])
            print("tianxiang: top ",(top+1)," arch val acc:",val)

        scheduler.step()

        if (epoch + 1) % args.val_interval == 0:
            validate(args, epoch, val_loader, device, model, criterion, supernet=True)
            utils.save_checkpoint({'state_dict': model.state_dict(), }, epoch + 1, tag=args.exp_name + '_super')

    utils.time_record(start)


if __name__ == '__main__':
    main()
