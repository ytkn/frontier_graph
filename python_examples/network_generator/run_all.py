import networkx as nx
from torchviz import make_dot
import torch
import random

from typing import List, Dict, Callable

from test_data_generator import generate_graph
from frame_generator import FrameGenerator
from output_size_searcher import OutputSizeSearcher
from module_generator import NNModuleGenerator


def calc_network_quality(output_sizes: Dict[int, int], output_dims: Dict[int, int]) -> int:
    """ サイズの変化とバリエーションで評価 """
    return len(set(output_sizes.values())) * (max(output_sizes.values()) - min(output_sizes.values()))


def list_networks(
    g: nx.DiGraph,
    starts: List[int],
    ends: List[int],
    kernel_sizes: List[int],
    strides: List[int],
    output_channel_candidates: List[int],
    network_input_sizes: Dict[int, int],
    network_output_sizes: Dict[int, int],
    allow_param_in_concat: bool,
    n_networks: int,
    n_network_candidates: int,
    calc_network_quality: Callable[[Dict[int, int], Dict[int, int]], int]
):
    """
    有効なnetworkをn_networks件列挙します。
    1件に対しn_network_candidates件候補をあげ、calc_network_qualityの値が最大のものを選びます
    """
    networks = []
    while len(networks) < n_networks:
        frame = fg.sample_graph()
        oss = OutputSizeSearcher(frame, starts, ends, max(network_input_sizes.values()),
                                 allow_param_in_concat, kernel_sizes, strides)

        candidate_sizes = []
        for _ in range(n_network_candidates):
            # NOTE: n_seed_nodesによって出力の次元が１になる頂点数が左右される。グラフのサイズによって変更する方が良いかもしれない。
            output_dimensions = oss.sample_output_dimensions(n_seed_nodes=3)
            result = oss.sample_valid_output_size(network_input_sizes, output_dimensions)
            if result == False: break
            else: candidate_sizes.append((result, output_dimensions))

        if len(candidate_sizes) == 0: continue

        output_sizes, output_dimensions = max(candidate_sizes, key=lambda x: calc_network_quality(x[0], x[1]))
        mg = NNModuleGenerator(frame, starts, ends, network_input_sizes, output_sizes,
                               output_dimensions, network_output_sizes, kernel_sizes, strides)

        module = mg.run(mg.calc_output_channels(output_channel_candidates, 3))
        networks.append(module)
    return networks


if __name__ == "__main__":
    random.seed(10)
    g, starts, ends = generate_graph(1, 12, 13, 1)
    kernel_sizes = [1, 2, 3]
    strides = [1, 2, 3]
    output_channel_candidates = [32, 64, 128, 192]
    network_input_sizes = {v: 224 for v in starts}
    network_output_sizes = {v: 1 for v in ends}
    allow_param_in_concat = True
    n_networks = 100
    n_network_candidates = 10

    fg = FrameGenerator(g, starts, ends)
    dryrun_args = tuple([torch.rand(1, 3, sz, sz) for sz in network_input_sizes.values()])

    networks = list_networks(
        g, starts, ends, kernel_sizes, strides,
        output_channel_candidates, network_input_sizes,
        network_output_sizes, allow_param_in_concat,
        n_networks, n_network_candidates, calc_network_quality)

    for idx, network in enumerate(networks):
        print(network)
        out = network(*dryrun_args)
        dot = make_dot(out)
        dot.format = 'png'
        dot.render(f'test_outputs/graph_image_{idx}')
