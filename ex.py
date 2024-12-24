# import numpy as np
# import torch
# loaded_npy = np.load('/Users/chtw2001/Documents/lab/MONET/codes/data/WomenClothing/image_feature.npy', allow_pickle=True)
# print(type(loaded_npy))
# print(loaded_npy.shape)
# image_feats = torch.tensor(loaded_npy)
# print(type(image_feats))
# print(image_feats.shape)


# # nonzero_idx = [(0, 1), (1, 0), (10, 1), (20, 9)]
# # nonzero_idx = torch.tensor(nonzero_idx)

# # nonzero_idx = nonzero_idx.T
# # nonzero_idx[1] = nonzero_idx[1] + 100
# # new_nonzero_idx = torch.cat(
# #     [nonzero_idx, torch.stack([nonzero_idx[1], nonzero_idx[0]], dim=0)], dim=1
# # )

# # # print(new_nonzero_idx)
# # # print(nonzero_idx)
# # # print(torch.stack([nonzero_idx[1], nonzero_idx[0]], dim=0))
# # # weight = torch.ones((new_nonzero_idx.size(1))).view(-1, 1)
# # # print(weight)
# # print(nonzero_idx)
# # print(nonzero_idx.size(1))
# # print(nonzero_idx.size(0))


dict_ = {'key': ['value']}
dict_2 = {'key': ['value2']}
dict_3 = dict_['key'] + dict_2['key']
print(dict_3)