#!/usr/bin/env python
import copy
from collections import OrderedDict

import torch
import torch.nn as nn
import numpy as np
import torchex.nn as exnn
import networkx as nx
from frontier_graph import NetworkxInterface

from inferno.extensions.layers.reshape import Concatenate
from inferno.extensions.containers import Graph


def conv2d(out_channels, kernel_size, stride):
    return exnn.Conv2d(out_channels=out_channels,
                       kernel_size=kernel_size,
                       stride=stride)


class FlattenLinear(nn.Module):
    def __init__(self, out_channels):
        super(FlattenLinear, self).__init__()
        self.out_channels = out_channels
        self.linear = exnn.Linear(self.out_channels)

    def forward(self, x):
        if len(x.shape) == 4:
            B, _, _, _ = x.shape
            x = x.reshape(B, -1)
        return self.linear(x)


class BaseNetwork(nn.Module):
    def __init__(self, edge_idx_list, edge_list, layers):
        super(BaseNetwork, self).__init__()
        self.edge_idx_list = edge_idx_list
        self.edge_list = edge_list
        self.layers = layers

    def forward(self, x1, x2):
        pass


class ModuleGen:
    def __init__(self):
        self.layer = []
        self.layer_dict = OrderedDict()
        self.layer_dict['concat'] = 0
        self._len = None

    def register(self, module_name: str, **params):
        self.layer.append((module_name, params))
        self.layer_dict[module_name] = 0
        for k in params:
            self.layer_dict[k] = 0

    def __getitem__(self, idx):
        module, vec = self.construct(idx)
        return module, vec

    def construct(self, idx):
        _layer_dict = copy.deepcopy(self.layer_dict)
        (module_name, params) = self.layer[idx]
        _layer_dict[module_name] = 1
        for k, v in params.items():
            _layer_dict[k] = v
        vec = list(_layer_dict.values())
        if module_name == 'conv2d':
            return conv2d(**params), vec
        elif module_name == 'linear':
            return FlattenLinear(**params), vec
        elif module_name == 'relu':
            return nn.ReLU(), vec
        elif module_name == 'identity':
            return nn.Identity(), vec

    def get_linear(self, out_channels):
        _layer_dict = copy.deepcopy(self.layer_dict)
        _layer_dict['linear'] = 1
        _layer_dict['out_channels'] = out_channels
        vec = list(_layer_dict.values())
        return FlattenLinear(out_channels), vec

    def get_identity_vec(self):
        _layer_dict = copy.deepcopy(self.layer_dict)
        _layer_dict['identity'] = 1
        vec = list(_layer_dict.values())
        return vec

    def get_cat(self):
        _layer_dict = copy.deepcopy(self.layer_dict)
        _layer_dict['concat'] = 1
        vec = list(_layer_dict.values())
        return Concatenate(), vec

    def get_empty_mat(self, n_node: int):
        _layer_dict = copy.deepcopy(self.layer_dict)
        n_features = len(_layer_dict.values())
        mat = np.zeros((n_node, n_features))
        return mat

    def __len__(self):
        if self._len is None:
            self._len = len(self.layer)
        return self._len


class NetworkGeneratar:
    def __init__(self, graph, starts, ends, max_samples, dryrun_args):
        self.graph = graph
        self.starts = starts
        self.ends = ends
        self.dryrun_args = dryrun_args
        self.modulegen = ModuleGen()
        self.modulegen.register('conv2d', out_channels=8, kernel_size=1, stride=1)
        self.modulegen.register('conv2d', out_channels=16, kernel_size=1, stride=1)
        self.modulegen.register('conv2d', out_channels=32, kernel_size=1, stride=1)
        self.modulegen.register('linear', out_channels=32)
        self.modulegen.register('linear', out_channels=64)
        self.modulegen.register('linear', out_channels=128)
        self.modulegen.register('relu')
        self.modulegen.register('identity')
        self.interface = NetworkxInterface(g)
        self.subgraph = self.get_subgraph(starts, ends, max_samples)
        self.n_subgraph = len(self.subgraph)
        self._len = None

    def get_subgraph(self, starts, ends, max_samples):
        return self.interface.sample(starts, ends, max_samples)

    def _construct_module(self, edge_list, _idx):
        module = Graph()
        for i in self.starts:
            vec = self.modulegen.get_identity_vec()
            module.add_input_node(f'{i}', vec=vec)
        node_dict = {}
        for (src, dst) in [list(self.graph.edges())[i - 1] for i in edge_list]:
            if not dst in node_dict.keys():
                node_dict[dst] = [src]
            else:
                node_dict[dst].append(src)
        for key, previous in sorted(node_dict.items(), key=lambda x: x[0]):
            layer_idx = _idx % len(self.modulegen)
            _idx //= len(self.modulegen)
            if len(previous) == 1:
                mod, vec = self.modulegen[layer_idx]
                module.add_node(f'{key}', mod, previous=[str(p) for p in previous], vec=vec)
            else:
                mod, vec = self.modulegen.get_cat()
                module.add_node(f'{key}', mod, previous=[str(p) for p in previous], vec=vec)
        mod, vec = self.modulegen.get_linear(10)
        module.add_node(f'{int(key) + 1}', mod, vec=vec, previous=[f'{key}'])
        vec = self.modulegen.get_identity_vec()
        module.add_output_node(f'{int(key) + 2}', f'{int(key) + 1}', vec=vec)
        edges = [[int(e[0]) - 1, int(e[1]) - 1] for e in module.graph.edges()]
        node_features = self.modulegen.get_empty_mat(int(key) + 2)
        for node in module.graph.nodes(data=True):
            idx = int(node[0]) - 1
            node_features[idx, :] = node[1]['vec']
        y = module(*self.dryrun_args)
        return module, edges, np.vstack(node_features)

    def __iter__(self):
        self.counter = 0
        return self

    def __next__(self):
        if self.counter <= len(self):
            self.counter += 1
            while True:
                try:
                    module, edges, node_features = self[self.counter]
                    module(*self.dryrun_args)
                    break
                except RuntimeError as e:
                    self.counter += 1
                    pass
            return module, edges, node_features
        else:
            raise StopIteration

    def __getitem__(self, idx):
        if idx >= len(self):
            raise IndexError
        _idx = idx
        subgraph_idx = _idx % self.n_subgraph
        edge_list = self.subgraph[subgraph_idx]
        _idx //= self.n_subgraph
        module = self._construct_module(edge_list, _idx)
        return module

    def __len__(self):
        if self._len is None:
            n_layer = len(self.modulegen)
            n = 0
            for graph in self.subgraph:
                n_edges = len(graph)  # return number of edges
                n += n_layer ** n_edges
            self._len = n
        return self._len


if __name__ == "__main__":
    g = nx.DiGraph()
    starts = [1, 2]
    ends = [9, ]
    g.add_edge(1, 3)
    g.add_edge(2, 4)
    g.add_edge(3, 5)
    g.add_edge(3, 6)
    g.add_edge(4, 5)
    g.add_edge(4, 7)
    g.add_edge(5, 6)
    g.add_edge(5, 7)
    g.add_edge(5, 8)
    g.add_edge(6, 8)
    g.add_edge(7, 8)
    g.add_edge(8, 9)
    ns = NetworkxInterface(g)
    graphs = ns.sample(starts, ends, 100)
    x = torch.rand(1, 3, 28, 28)
    ng = NetworkGeneratar(g, starts, ends, 100, dryrun_args=(x, x))
    for n in ng:
        module = n[0]
        edges = n[1]
        node_features = n[2]
        print(module)
