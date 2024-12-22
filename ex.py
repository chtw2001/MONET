import numpy as np
import torch
# loaded_npy = np.load('/Users/chtw2001/Documents/lab/MONET/codes/data/WomenClothing/image_feature.npy', allow_pickle=True)
# data = loaded_npy.item()  # 객체로 변환
# i = '(4096,)'
# for key in data.keys():
#     if i != str(data[key].shape):
#         print(str(data[key].shape))

nonzero_idx = [(0, 1), (1, 0), (10, 1), (20, 9)]
nonzero_idx = torch.tensor(nonzero_idx)

nonzero_idx = nonzero_idx.T
nonzero_idx[1] = nonzero_idx[1] + 100
new_nonzero_idx = torch.cat(
    [nonzero_idx, torch.stack([nonzero_idx[1], nonzero_idx[0]], dim=0)], dim=1
)

# print(new_nonzero_idx)
# print(nonzero_idx)
# print(torch.stack([nonzero_idx[1], nonzero_idx[0]], dim=0))
# weight = torch.ones((new_nonzero_idx.size(1))).view(-1, 1)
# print(weight)
print(nonzero_idx)
print(nonzero_idx.size(1))
print(nonzero_idx.size(0))


