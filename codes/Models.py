import torch
import torch.nn as nn
import torch.nn.functional as F
from torch.nn import Parameter
from torch_geometric.nn.conv import MessagePassing
from torch_geometric.utils.num_nodes import maybe_num_nodes
from torch_scatter import scatter_add


def normalize_laplacian(edge_index, edge_weight):
    # 모든 user, item 노드의 수
    num_nodes = maybe_num_nodes(edge_index)
    row, col = edge_index[0], edge_index[1]
    deg = scatter_add(edge_weight, row, dim=0, dim_size=num_nodes)

    deg_inv_sqrt = deg.pow_(-0.5)
    deg_inv_sqrt.masked_fill_(deg_inv_sqrt == float("inf"), 0)
    edge_weight = deg_inv_sqrt[row] * edge_weight * deg_inv_sqrt[col]
    return edge_weight


class Our_GCNs(MessagePassing):
    # aggr: The aggregation scheme to use
    def __init__(self, in_channels, out_channels):
        super(Our_GCNs, self).__init__(aggr="add")
        self.in_channels = in_channels
        self.out_channels = out_channels

    def forward(self, x, edge_index, weight_vector, size=None):
        self.weight_vector = weight_vector
        return self.propagate(edge_index, size=size, x=x)

    # @override
    def message(self, x_j):
        return x_j * self.weight_vector

    # @override
    def update(self, aggr_out):
        return aggr_out


from torch_geometric.nn.inits import uniform


class Nonlinear_GCNs(MessagePassing):
    def __init__(self, in_channels, out_channels):
        super(Nonlinear_GCNs, self).__init__(aggr="add")
        self.in_channels = in_channels
        self.out_channels = out_channels
        self.weight = Parameter(torch.Tensor(self.in_channels, out_channels))
        self.reset_parameters()

    def reset_parameters(self):
        uniform(self.in_channels, self.weight)

    def forward(self, x, edge_index, weight_vector, size=None):
        x = torch.matmul(x, self.weight)
        self.weight_vector = weight_vector
        return self.propagate(edge_index, size=size, x=x)

    def message(self, x_j):
        return x_j * self.weight_vector

    def update(self, aggr_out):
        return aggr_out


class MeGCN(nn.Module):
    def __init__(
        self,
        n_users,
        n_items,
        n_layers,
        has_norm,
        feat_embed_dim,
        nonzero_idx,
        image_feats,
        text_feats,
        alpha,
        agg,
        cf,
        cf_gcn,
        lightgcn,
    ):
        super(MeGCN, self).__init__()
        self.n_users = n_users
        self.n_items = n_items
        self.n_layers = n_layers
        self.has_norm = has_norm
        self.feat_embed_dim = feat_embed_dim
        # (2, max(user_num, item_num))
        self.nonzero_idx = torch.tensor(nonzero_idx).cuda().long().T
        self.alpha = alpha
        self.agg = agg
        self.cf = cf
        self.cf_gcn = cf_gcn
        self.lightgcn = lightgcn

        self.image_preference = nn.Embedding(self.n_users, self.feat_embed_dim)
        self.text_preference = nn.Embedding(self.n_users, self.feat_embed_dim)
        nn.init.xavier_uniform_(self.image_preference.weight)
        nn.init.xavier_uniform_(self.text_preference.weight)

        # image_feats, text_feats는 이미 학습 된 임베딩 된 결과!
        self.image_embedding = nn.Embedding.from_pretrained(
            torch.tensor(image_feats, dtype=torch.float), freeze=True
        )  # [# of items, 4096]
        self.text_embedding = nn.Embedding.from_pretrained(
            torch.tensor(text_feats, dtype=torch.float), freeze=True
        )  # [# of items, 1024]

        if self.cf:
            self.user_embedding = nn.Embedding(self.n_users, self.feat_embed_dim)
            self.item_embedding = nn.Embedding(self.n_items, self.feat_embed_dim)
            nn.init.xavier_uniform_(self.user_embedding.weight)
            nn.init.xavier_uniform_(self.item_embedding.weight)

        self.image_trs = nn.Linear(image_feats.shape[1], self.feat_embed_dim)
        self.text_trs = nn.Linear(text_feats.shape[1], self.feat_embed_dim)

        if not self.cf:
            if self.agg == "fc":
                # multimodal의 개수
                self.transform = nn.Linear(self.feat_embed_dim * 2, self.feat_embed_dim)
            elif self.agg == "weighted_sum":
                # 임베딩 된 결과를 대상으로 가중치를 학습시켜서 진행
                self.modal_weight = nn.Parameter(torch.Tensor([0.5, 0.5]))
                self.softmax = nn.Softmax(dim=0)
        else:
            if self.agg == "fc":
                # multimodal의 개수
                self.transform = nn.Linear(self.feat_embed_dim * 3, self.feat_embed_dim)
            elif self.agg == "weighted_sum":
                self.modal_weight = nn.Parameter(torch.Tensor([0.33, 0.33, 0.33]))
                self.softmax = nn.Softmax(dim=0)

        self.layers = nn.ModuleList(
            [
                Our_GCNs(self.feat_embed_dim, self.feat_embed_dim)
                for _ in range(self.n_layers)
            ]
        )

    def forward(self, edge_index, edge_weight, _eval=False):
        # transform
        # 4096 -> 64
        # (item_num, 64)
        image_emb = self.image_trs(
            self.image_embedding.weight
        )  # [# of items, feat_embed_dim]
        # 1024 -> 64
        # (item_num, 64)
        text_emb = self.text_trs(
            self.text_embedding.weight
        )  # [# of items, feat_embed_dim]

        # True. l2노름으로 정규화
        if self.has_norm:
            image_emb = F.normalize(image_emb)
            text_emb = F.normalize(text_emb)
    
        # self.image_preference.weight -> (user_num, 64)
        image_preference = self.image_preference.weight
        text_preference = self.text_preference.weight

        # propagate
        # ((user_num + item_num), 64)
        ego_image_emb = torch.cat([image_preference, image_emb], dim=0)
        ego_text_emb = torch.cat([text_preference, text_emb], dim=0)

        if self.cf:
            user_emb = self.user_embedding.weight
            item_emb = self.item_embedding.weight
            # ((user_num + item_num), 64)
            ego_cf_emb = torch.cat([user_emb, item_emb], dim=0)
            if self.cf_gcn == "LightGCN":
                all_cf_emb = [ego_cf_emb]

        if self.lightgcn:
            all_image_emb = [ego_image_emb]
            all_text_emb = [ego_text_emb]

        for layer in self.layers:
            if not self.lightgcn:
                # (x, index, weight)
                # ego_image/text_emb를 계속 갱신
                side_image_emb = layer(ego_image_emb, edge_index, edge_weight)
                side_text_emb = layer(ego_text_emb, edge_index, edge_weight)

                ego_image_emb = side_image_emb + self.alpha * ego_image_emb
                ego_text_emb = side_text_emb + self.alpha * ego_text_emb
            else:
                # 이전 ego_image/text_emb에 대해서 계산
                side_image_emb = layer(ego_image_emb, edge_index, edge_weight)
                side_text_emb = layer(ego_text_emb, edge_index, edge_weight)
                ego_image_emb = side_image_emb
                ego_text_emb = side_text_emb
                # ego_image/text_emb 누적 후 stack, mean
                all_image_emb += [ego_image_emb]
                all_text_emb += [ego_text_emb]
            if self.cf:
                if self.cf_gcn == "MeGCN":
                    # ego_cf_emb를 계속 갱신
                    side_cf_emb = layer(ego_cf_emb, edge_index, edge_weight)
                    ego_cf_emb = side_cf_emb + self.alpha * ego_cf_emb
                    # self.alpha -> ego_cf_emb의 가중치
                elif self.cf_gcn == "LightGCN":
                    # ego_cf_emb를 누적하여 추후에 stack, mean
                    side_cf_emb = layer(ego_cf_emb, edge_index, edge_weight)
                    ego_cf_emb = side_cf_emb
                    all_cf_emb += [ego_cf_emb]

        if not self.lightgcn:
            final_image_preference, final_image_emb = torch.split(
                ego_image_emb, [self.n_users, self.n_items], dim=0
            )
            final_text_preference, final_text_emb = torch.split(
                ego_text_emb, [self.n_users, self.n_items], dim=0
            )
        else:
            # stack, mean 과정
            all_image_emb = torch.stack(all_image_emb, dim=1)
            all_image_emb = all_image_emb.mean(dim=1, keepdim=False)
            final_image_preference, final_image_emb = torch.split(
                all_image_emb, [self.n_users, self.n_items], dim=0
            )

            all_text_emb = torch.stack(all_text_emb, dim=1)
            all_text_emb = all_text_emb.mean(dim=1, keepdim=False)
            final_text_preference, final_text_emb = torch.split(
                all_text_emb, [self.n_users, self.n_items], dim=0
            )

        if self.cf:
            if self.cf_gcn == "MeGCN":
                final_cf_user_emb, final_cf_item_emb = torch.split(
                    ego_cf_emb, [self.n_users, self.n_items], dim=0
                )
            elif self.cf_gcn == "LightGCN":
                # stack, mean 과정
                all_cf_emb = torch.stack(all_cf_emb, dim=1)
                all_cf_emb = all_cf_emb.mean(dim=1, keepdim=False)
                final_cf_user_emb, final_cf_item_emb = torch.split(
                    all_cf_emb, [self.n_users, self.n_items], dim=0
                )

        # final_image_preference, final_image_emb
        # final_text_preference, final_text_emb
        # final_cf_user_emb, final_cf_item_emb 출력
        if _eval:
            return ego_image_emb, ego_text_emb

        if not self.cf:
            if self.agg == "concat":
                items = torch.cat(
                    [final_image_emb, final_text_emb], dim=1
                )  # [# of items, feat_embed_dim * 2]
                user_preference = torch.cat(
                    [final_image_preference, final_text_preference], dim=1
                )  # [# of users, feat_embed_dim * 2]
            elif self.agg == "sum":
                items = final_image_emb + final_text_emb  # [# of items, feat_embed_dim]
                user_preference = (
                    final_image_preference + final_text_preference
                )  # [# of users, feat_embed_dim]
            elif self.agg == "weighted_sum":
                # [0.5, 0.5]
                weight = self.softmax(self.modal_weight)
                items = (
                    weight[0] * final_image_emb + weight[1] * final_text_emb
                )  # [# of items, feat_embed_dim]
                user_preference = (
                    weight[0] * final_image_preference
                    + weight[1] * final_text_preference
                )  # [# of users, feat_embed_dim]
            elif self.agg == "fc":
                # linear transfor -> 64
                items = self.transform(
                    torch.cat([final_image_emb, final_text_emb], dim=1)
                )  # [# of items, feat_embed_dim]
                user_preference = self.transform(
                    torch.cat([final_image_preference, final_text_preference], dim=1)
                )  # [# of users, feat_embed_dim]
        else:
            if self.agg == "concat":
                items = torch.cat(
                    [final_image_emb, final_text_emb, final_cf_item_emb], dim=1
                )  # [# of items, feat_embed_dim * 2]
                user_preference = torch.cat(
                    [final_image_preference, final_text_preference, final_cf_user_emb],
                    dim=1,
                )  # [# of users, feat_embed_dim * 2]
            elif self.agg == "sum":
                items = (
                    final_image_emb + final_text_emb + final_cf_item_emb
                )  # [# of items, feat_embed_dim]
                user_preference = (
                    final_image_preference + final_text_preference + final_cf_user_emb
                )  # [# of users, feat_embed_dim]
            elif self.agg == "weighted_sum":
                weight = self.softmax(self.modal_weight)
                items = (
                    weight[0] * final_image_emb
                    + weight[1] * final_text_emb
                    + weight[2] * final_cf_item_emb
                )  # [# of items, feat_embed_dim]
                user_preference = (
                    weight[0] * final_image_preference
                    + weight[1] * final_text_preference
                    + weight[2] * final_cf_user_emb
                )  # [# of users, feat_embed_dim]
            elif self.agg == "fc":
                items = self.transform(
                    torch.cat(
                        [final_image_emb, final_text_emb, final_cf_item_emb], dim=1
                    )
                )  # [# of items, feat_embed_dim]
                user_preference = self.transform(
                    torch.cat(
                        [
                            final_image_preference,
                            final_text_preference,
                            final_cf_user_emb,
                        ],
                        dim=1,
                    )
                )  # [# of users, feat_embed_dim]

        # user preference of image/text, user CF embedding
        # embedding of image/text, item CF embedding
        return user_preference, items


class MONET(nn.Module):
    def __init__(
        self,
        n_users,
        n_items,
        feat_embed_dim,
        nonzero_idx,
        has_norm,
        image_feats,
        text_feats,
        n_layers,
        alpha,
        beta,
        agg,
        cf,
        cf_gcn,
        lightgcn,
    ):
        super(MONET, self).__init__()
        self.n_users = n_users
        self.n_items = n_items
        self.feat_embed_dim = feat_embed_dim
        self.n_layers = n_layers
        self.nonzero_idx = nonzero_idx
        self.alpha = alpha
        self.beta = beta
        self.agg = agg
        self.image_feats = torch.tensor(image_feats, dtype=torch.float).cuda()
        self.text_feats = torch.tensor(text_feats, dtype=torch.float).cuda()

        self.megcn = MeGCN(
            self.n_users,
            self.n_items,
            self.n_layers,
            has_norm,
            self.feat_embed_dim,
            self.nonzero_idx,
            image_feats,
            text_feats,
            self.alpha,
            self.agg,
            cf,
            cf_gcn,
            lightgcn,
        )

        # shape -> (2, max(user_num, item_num))
        nonzero_idx = torch.tensor(self.nonzero_idx).cuda().long().T
        # item idx에 user의 수를 더하여 겹치지 않게 설정
        nonzero_idx[1] = nonzero_idx[1] + self.n_users
        # shape -> (2, (user_num + item_num))
        # user -> item, item -> user
        self.edge_index = torch.cat(
            [nonzero_idx, torch.stack([nonzero_idx[1], nonzero_idx[0]], dim=0)], dim=1
        )
        # shape -> ((user_num + item_num), 1)
        self.edge_weight = torch.ones((self.edge_index.size(1))).cuda().view(-1, 1)
        # shape -> ((user_num + item_num), 1)
        self.edge_weight = normalize_laplacian(self.edge_index, self.edge_weight)

        # shape -> (2, max(user_num, item_num))
        nonzero_idx = torch.tensor(self.nonzero_idx).cuda().long().T
        # user-item interaction tensor
        self.adj = (
            torch.sparse.FloatTensor(
                nonzero_idx,
                torch.ones((nonzero_idx.size(1))).cuda(),
                (self.n_users, self.n_items),
            )
            .to_dense()
            .cuda()
        )

    def forward(self, _eval=False):
        if _eval:
            img, txt = self.megcn(self.edge_index, self.edge_weight, _eval=True)
            return img, txt

        user, items = self.megcn(self.edge_index, self.edge_weight, _eval=False)

        return user, items

    def bpr_loss(self, user_emb, item_emb, users, pos_items, neg_items, target_aware):
        current_user_emb = user_emb[users]
        pos_item_emb = item_emb[pos_items]
        neg_item_emb = item_emb[neg_items]

        if target_aware:
            # target-aware
            # (item_num, item_num) shape
            # item간 유사도를 계산!
            item_item = torch.mm(item_emb, item_emb.T)
            pos_item_query = item_item[pos_items, :]  # (batch_size, n_items)
            neg_item_query = item_item[neg_items, :]  # (batch_size, n_items)
            # element-wise -> 0인 값은 -1e9로 세팅 -> softmax함수 통과
            pos_target_user_alpha = torch.softmax(
                torch.multiply(pos_item_query, self.adj[users, :]).masked_fill(
                    self.adj[users, :] == 0, -1e9
                ),
                dim=1,
            )  # (batch_size, n_items)
            # 여기서 -1e9로 세팅되지 않는 값이 별로 없을 것 같은데, 
            # 그 값들이 softmax를 통과하면 더 영향이 커지지 않는가?
            # beta로 작은 가중치를 주어도 크게 작용되지 않을까?
            neg_target_user_alpha = torch.softmax(
                torch.multiply(neg_item_query, self.adj[users, :]).masked_fill(
                    self.adj[users, :] == 0, -1e9
                ),
                dim=1,
            )  # (batch_size, n_items)
            # (batch_size, 64)
            pos_target_user = torch.mm(
                pos_target_user_alpha, item_emb
            )  # (batch_size, dim)
            neg_target_user = torch.mm(
                neg_target_user_alpha, item_emb
            )  # (batch_size, dim)

            # predictor
            # self.beta -> 0.3
            # cf에 0.7, target aware에 0.3 가중치 곱해서 score계산
            pos_scores = (1 - self.beta) * torch.sum(
                torch.mul(current_user_emb, pos_item_emb), dim=1
            ) + self.beta * torch.sum(torch.mul(pos_target_user, pos_item_emb), dim=1)
            neg_scores = (1 - self.beta) * torch.sum(
                torch.mul(current_user_emb, neg_item_emb), dim=1
            ) + self.beta * torch.sum(torch.mul(neg_target_user, neg_item_emb), dim=1)
        else:
            pos_scores = torch.sum(torch.mul(current_user_emb, pos_item_emb), dim=1)
            neg_scores = torch.sum(torch.mul(current_user_emb, neg_item_emb), dim=1)

        maxi = F.logsigmoid(pos_scores - neg_scores)
        mf_loss = -torch.mean(maxi)

        # l2노름은 아닌데 비슷한 정규화 항. 제곱의 합에 1/2를 하여 더함
        regularizer = (
            1.0 / 2 * (pos_item_emb**2).sum()
            + 1.0 / 2 * (neg_item_emb**2).sum()
            + 1.0 / 2 * (current_user_emb**2).sum()
        )
        # 배치 만큼 나누기
        emb_loss = regularizer / pos_item_emb.size(0)

        reg_loss = 0.0

        return mf_loss, emb_loss, reg_loss
