import time
from collections import defaultdict
import util
import networkx as nx
from itertools import islice
import numpy as np
import os
import ctypes

INT_PTR = ctypes.POINTER(ctypes.c_int)
INT_PTR_PTR = ctypes.POINTER(INT_PTR)

class SolutionData(ctypes.Structure):
    _fields_ = [
        ("x_indices", ctypes.POINTER(ctypes.c_int)),
        ("x_values", ctypes.POINTER(ctypes.c_double)),
        ("x_count", ctypes.c_int),
        ("l_indices", ctypes.POINTER(ctypes.c_int)),
        ("l_values", ctypes.POINTER(ctypes.c_double)),
        ("l_count", ctypes.c_int),
        ("w_indices", ctypes.POINTER(ctypes.c_int)),
        ("w_values", ctypes.POINTER(ctypes.c_double)),
        ("w_count", ctypes.c_int),
        ("y_indices", ctypes.POINTER(ctypes.c_int)),
        ("y_values", ctypes.POINTER(ctypes.c_double)),
        ("y_count", ctypes.c_int),
    ]

def load_solver(N, max_distance):
   
    gurobi_lib_path = '/Library/gurobi1202/mac64/lib'
    if 'DYLD_LIBRARY_PATH' in os.environ:
        os.environ['DYLD_LIBRARY_PATH'] = f"{os.environ['DYLD_LIBRARY_PATH']}:{gurobi_lib_path}"
    else:
        os.environ['DYLD_LIBRARY_PATH'] = gurobi_lib_path
        
    lib_path = os.path.join(os.path.dirname(__file__), "yjr_solver.so")
    
    if not os.path.exists(lib_path):
        raise FileNotFoundError(f"C 라이브러리를 찾을 수 없습니다: {lib_path}")
    
    
    lib = ctypes.CDLL(lib_path)
    
    
    lib.solve_mip.argtypes = [
        ctypes.c_int,     
        ctypes.c_int,     
        ctypes.c_int,     
        ctypes.c_int,     
        ctypes.c_int,     
        INT_PTR_PTR,
        ctypes.POINTER(ctypes.c_int * N),
        INT_PTR_PTR,
        ctypes.c_double,      
        ctypes.c_int,
        INT_PTR_PTR,
        ctypes.c_int,
        ctypes.POINTER(ctypes.c_int * (max_distance + 1))
    ]
    
    lib.solve_mip.restype = ctypes.POINTER(SolutionData)
    
    lib.free_solution_data.argtypes = [ctypes.POINTER(SolutionData)]
    lib.free_solution_data.restype = None
    
    return lib

    
def algorithm(prob_info, timelimit=60):
    """메인 알고리즘 함수"""
    start_time = time.time()
    curr_solution = heu_algorithm(prob_info, timelimit)
    
    
    
    N, E, K, P, F = prob_info['N'], prob_info['E'], prob_info['K'], prob_info['P'], prob_info['F']
    grid_graph = prob_info['grid_graph']

    
    G = nx.Graph()
    G.add_nodes_from(range(N))
    G.add_edges_from(set(tuple(sorted(e)) for e in E))
    edges = [(i,j) for i in range(N) for j in range(N) if [i,j] in E or [j,i] in E]
    edges = [(i,j) for i,j in edges if i > 0]
    
    
    k_count = len(K)
    k_data_np = np.zeros((k_count, 3), dtype=np.int32)
    for i, ((o, d), quantity) in enumerate(K):
        k_data_np[i, 0] = o
        k_data_np[i, 1] = d
        k_data_np[i, 2] = quantity
    
    
    c_k_data_ptr = (INT_PTR * k_count)()
    for i in range(k_count):
        row = (ctypes.c_int * 3)()
        for j in range(3):
            row[j] = int(k_data_np[i, j])
        c_k_data_ptr[i] = ctypes.cast(row, INT_PTR)
    
    
    def ksp_average_lengths(G, source, k=10, weight=None):
        def path_len(path):
            if weight is None:
                return len(path) - 1
            return sum(G[u][v].get(weight, 1.0) for u, v in zip(path, path[1:]))

        avg = {}
        for target in G.nodes:
            if target == source:
                avg[target] = 0.0
                continue
            try:
                gen = nx.shortest_simple_paths(G, source, target, weight=weight)
                lengths = [path_len(p) for p in islice(gen, k)]
                
                if lengths:
                    
                    
                    
                    avg[target] = len(lengths) / sum(1 / l for l in lengths)
                    
            except nx.NetworkXNoPath:
                pass

        return avg

        
    
    distances = nx.shortest_path_length(G, source=0)
    
    max_distance = max(distances.values())
    
    
    distance_groups = [[] for _ in range(max_distance + 1)]
    for node, dist in distances.items():
        distance_groups[dist].append(node)

    
    max_cols = max(len(group) for group in distance_groups)
    matrix = np.full((max_distance + 1, max_cols), -1)
    for i, group in enumerate(distance_groups):
        if group:
            matrix[i, :len(group)] = group
    matrix_ptr = (INT_PTR * (max_distance + 1))()
    for i in range(max_distance + 1):
        
        row = (ctypes.c_int * max_cols)()
        for j in range(max_cols):
            row[j] = int(matrix[i, j])
        
        matrix_ptr[i] = ctypes.cast(row, INT_PTR)
            
    
    count_array = np.zeros(max_distance + 1, dtype=int)
    for node, dist in distances.items():
        count_array[dist] += 1

    
    cumulative_array = np.cumsum(count_array)
    cumulative_array_c = (ctypes.c_int * (max_distance + 1))()
    for i in range(max_distance + 1):
        cumulative_array_c[i] = int(cumulative_array[i])

    
    
    
    
    
    sorted_nodes = sorted(distances, key=distances.get)
    sorted_nodes_arr = (ctypes.c_int * N)()
    for i in range(N):
        sorted_nodes_arr[i] = int(sorted_nodes[i])
    
    
    edges = [(i, j) for i in range(N) for j in range(N) 
             if [i, j] in E or [j, i] in E]
    edges = [(i, j) for i, j in edges if i > 0]
    edge_count = len(edges)
    
    
    edge_lst_ptr = (INT_PTR * edge_count)()
    for k in range(edge_count):
        row = (ctypes.c_int * 2)()
        row[0] = int(edges[k][0])
        row[1] = int(edges[k][1])
        edge_lst_ptr[k] = ctypes.cast(row, INT_PTR)
    
    
    elapsed_time = time.time() - start_time
    remaining_time = max(1, timelimit - elapsed_time)
    
    
    lib = load_solver(N, max_distance)
    
    
    lib.solve_mip.argtypes = [
        ctypes.c_int,     
        ctypes.c_int,     
        ctypes.c_int,     
        ctypes.c_int,     
        ctypes.c_int,     
        INT_PTR_PTR,      
        ctypes.POINTER(ctypes.c_int * N),  
        INT_PTR_PTR,      
        ctypes.c_double,   
        ctypes.c_int,
        INT_PTR_PTR,
        ctypes.c_int,
        ctypes.POINTER(ctypes.c_int * (max_distance + 1))
    ]
    
    
    
    
    
    
    c_solution = lib.solve_mip(
        ctypes.c_int(N),
        ctypes.c_int(P),
        ctypes.c_int(k_count),
        ctypes.c_int(F),
        ctypes.c_int(edge_count),
        c_k_data_ptr,
        sorted_nodes_arr,
        edge_lst_ptr,
        ctypes.c_double(remaining_time),
        ctypes.c_int(max_distance+1),
        matrix_ptr,
        ctypes.c_int(max_cols),
        cumulative_array_c,
    )
    
    if not c_solution:
        print("C solver returned NULL solution")
        return {p: [] for p in range(P)}
    
    
    sol_data = c_solution.contents
    
    
    class MockVar:
        def __init__(self, value):
            self.X = value
    
    
    x = {}
    for i in range(sol_data.x_count):
        p = sol_data.x_indices[i*4]
        node = sol_data.x_indices[i*4 + 1]
        q = sol_data.x_indices[i*4 + 2]
        r = sol_data.x_indices[i*4 + 3]
        value = sol_data.x_values[i]
        x[(p, node, q, r)] = MockVar(value)
    
    
    l = {}
    for i in range(sol_data.l_count):
        p = sol_data.l_indices[i*3]
        node_i = sol_data.l_indices[i*3 + 1]
        node_j = sol_data.l_indices[i*3 + 2]
        value = sol_data.l_values[i]
        l[(p, node_i, node_j)] = MockVar(value)
    
    
    w = {}
    for i in range(sol_data.w_count):
        p = sol_data.w_indices[i*2]
        node = sol_data.w_indices[i*2 + 1]
        value = sol_data.w_values[i]
        w[(p, node)] = MockVar(value)
    
    
    y = {}
    for i in range(sol_data.y_count):
        p = sol_data.y_indices[i*2]
        node = sol_data.y_indices[i*2 + 1]
        value = sol_data.y_values[i]
        y[(p, node)] = MockVar(value)
    
    
    lib.free_solution_data(c_solution)
    
    
    solution = parse_mip_solution(None, prob_info, x, y, w, l)
    
    print(f"Algorithm completed in {time.time() - start_time:.2f}s")
    
    if sol_data.x_count == 0: return curr_solution
    if getobj(prob_info, curr_solution) < getobj(prob_info, solution): return curr_solution
    
    return solution



def parse_mip_solution(model, prob_info, x, y, w, l):
    """
    MIP 솔루션에서 solution dictionary를 구성하는 함수
    """
    N, E, K, P, F = prob_info['N'], prob_info['E'], prob_info['K'], prob_info['P'], prob_info['F']
    
    
    adj_list = {i: [] for i in range(N)}
    for e in E:
        adj_list[e[0]].append(e[1])
        adj_list[e[1]].append(e[0])
    
    
    solution = {p: [] for p in range(P)}
    
    
    for p in range(P):
        port_routes = []
        rehandle = {p: [] for p in range(P)}
        print(f"\n=== Processing Port {p} ===")
        
        
        if p > 0:
            
            f_edges = []
            for var_name, var in l.items():
                if var_name[0] == p and var.X > 0.4:
                    f_edges.append((var_name[1], var_name[2]))
            
            
            for demand_idx, ((origin, dest), quantity) in enumerate(K):
                if dest == p:  
                    
                    for node in range(1, N):
                        try:
                            key = (p, node, origin, demand_idx)
                            if key in x and x[key].X > 0.5:
                                path = find_path_using_edges(node, 0, f_edges, adj_list)
                                if path:
                                    port_routes.append((path, demand_idx))
                        except Exception as e:
                            pass
                else:
                    
                    for node in range(1, N):
                        key = (p, node, origin, demand_idx)
                        if key in x and x[key].X > 0.5 and origin < p:
                            
                            w_key = (p, node)
                            if w_key in w and w[w_key].X > 0.5:
                                path = find_path_using_edges(node, 0, f_edges, adj_list)
                                if path:
                                    rehandle[p].append((node, demand_idx))
                                    port_routes.append((path, demand_idx))
        
        
        if p < P - 1:
            
            l_edges = []
            for var_name, var in l.items():
                if var_name[0] == p and var.X > 0.4:
                    l_edges.append((var_name[1], var_name[2]))
            
            
            for nd, dind in rehandle[p]:
                path = find_path_using_edges(0, nd, l_edges, adj_list)
                if path:
                    port_routes.append((path, dind))
            
            
            for demand_idx, ((origin, dest), quantity) in enumerate(K):
                if origin == p:  
                    loaded_count = 0
                    
                    
                    for node in range(1, N):
                        if loaded_count >= quantity:
                            break
                        
                        try:
                            if p + 1 < P:
                                key = (p + 1, node, p, demand_idx)
                                if key in x and x[key].X > 0.5:
                                    path = find_path_using_edges(0, node, l_edges, adj_list)
                                    if path:
                                        port_routes.append((path, demand_idx))
                                        loaded_count += 1
                        except Exception as e:
                            pass
        
        
        solution[p] = sort_routes_by_type(port_routes)
    
    return solution
def find_path_using_edges(start, end, flow_edges, adj_list):
    """
    Flow edges를 사용하여 start에서 end까지 경로 찾기
    """
    if start == end:
        return [start]
    
    
    flow_graph = {i: [] for i in range(len(adj_list))}
    for i, j in flow_edges:
        flow_graph[i].append(j)
        flow_graph[j].append(i)  
    
    
    from collections import deque
    queue = deque([(start, [start])])
    visited = set([start])
    
    while queue:
        node, path = queue.popleft()
        
        for neighbor in flow_graph[node]:
            if neighbor not in visited:
                new_path = path + [neighbor]
                if neighbor == end:
                    return new_path
                visited.add(neighbor)
                queue.append((neighbor, new_path))
    
    
    return find_shortest_path(start, end, adj_list)

def find_shortest_path(start, end, adj_list):
    """
    BFS로 최단 경로 찾기
    """
    from collections import deque
    
    queue = deque([(start, [start])])
    visited = set([start])
    
    while queue:
        node, path = queue.popleft()
        
        if node == end:
            return path
        
        for neighbor in adj_list[node]:
            if neighbor not in visited:
                visited.add(neighbor)
                queue.append((neighbor, path + [neighbor]))
    
    return None

def sort_routes_by_type(routes):
    """
    경로들을 타입별로 정렬 (하역 → 선적)
    """
    if not routes:
        return []
    
    unloading = []
    loading = []
    
    for route, demand_idx in routes:
        if route[-1] == 0:  
            unloading.append((route, demand_idx))
        elif route[0] == 0:  
            loading.append((route, demand_idx))
    
    
    unloading.sort(key=lambda x: len(x[0]))
    
    
    loading.sort(key=lambda x: len(x[0]), reverse=True)
    
    return unloading + loading

def getobj(prob_info, solution):

    N = prob_info['N']
    E = prob_info['E']
    E = set([(u,v) for (u,v) in E])
    K = prob_info['K']
    P = prob_info['P']
    F = prob_info['F']
    LB = prob_info['LB']

    # Current status of nodes
    # -1 means available (i.e. empty)
    # otherwise means occupied with a demand
    node_allocations = np.ones(N, dtype=int) * -1


    # All demands that should be in the cargo at leaving port p
    supposedly_loaded_demands_after_ports = {}

    for p in range(P):
        supposedly_loaded_demands_after_ports[p] = {}
        for k,((o,d),r) in enumerate(K):
            if o <= p < d:
                supposedly_loaded_demands_after_ports[p][k] = r

    obj = 0
    infeasibility = []


    if len(infeasibility) == 0:

        for p in range(P):
            if p not in solution:
                infeasibility.append(f'The solution does not contain route list for port {p}')

            route_list = solution[p]

            for route, k in route_list:
                if len(route) <= 1:
                    infeasibility.append(f'The length of the route {route} is less than 2')
                
                if min(route) < 0 or max(route) >= N:
                    infeasibility.append(f'The route {route} has invalid node index')

                if not all(isinstance(i, int) for i in route):
                    infeasibility.append(f'The route {route} has non-integer node index')
                
                if len(route) != len(set(route)):
                    infeasibility.append(f'The route {route} has a duplicated node index, i.e., the route should be simple.')
                
                if route[0] == 0:
                    # Loading route
                    loading_node = route[-1]
                    if node_allocations[loading_node] != -1:
                        infeasibility.append(f'The loading node {loading_node} from route {route} is already occupied by demand {node_allocations[loading_node]}')
                    
                    for i in route[:-1]:
                        if node_allocations[i] != -1:
                            infeasibility.append(f'The loading route {route} is blocked by node {i} that is occupied by demand {node_allocations[i]}')
                        
                    for (u,v) in zip(route[:-1], route[1:]):
                        if (u,v) not in E and (v,u) not in E:
                            infeasibility.append(f'The route {route} contains an invalid edge {(u,v)}')
                        
                    node_allocations[loading_node] = k

                elif route[-1] == 0:
                    # Unloading route
                    unloading_node = route[0]
                    if node_allocations[unloading_node] == -1:
                        infeasibility.append(f'The unloading node {unloading_node} from route {route} is not occupied by any demand')
                    
                    for i in route[1:]:
                        if node_allocations[i] != -1:
                            infeasibility.append(f'The unloading route {route} is blocked by node {i} that is occupied by demand {node_allocations[i]}')

                    for (u,v) in zip(route[:-1], route[1:]):
                        if (u,v) not in E and (v,u) not in E:
                            infeasibility.append(f'The route {route} contains an invalid edge {(u,v)}')
                        
                    node_allocations[unloading_node] = -1

                elif route[0] != 0 and route[-1] != 0:
                    # Rehandling route
                    unloading_node = route[0]
                    loading_node = route[-1]

                    if node_allocations[unloading_node] == -1:
                        infeasibility.append(f'The unloading node {unloading_node} from route {route} is not occupied by any demand')
                    if node_allocations[loading_node] != -1:
                        infeasibility.append(f'The loading node {loading_node} from route {route} is already occupied by demand {node_allocations[loading_node]}')
                    
                    for i in route[1:-1]:
                        if node_allocations[i] != -1:
                            infeasibility.append(f'The rehandling route {route} is blocked by node {i} that is occupied by demand {node_allocations[i]}')

                    for (u,v) in zip(route[:-1], route[1:]):
                        if (u,v) not in E and (v,u) not in E:
                            infeasibility.append(f'The route {route} contains an invalid edge {(u,v)}')
                        
                    node_allocations[loading_node] = k
                    node_allocations[unloading_node] = -1


                obj += F + len(route) - 1

      

    if len(infeasibility) == 0: # All checks are passed!
        # We reduce the objective value by the lower bound
        # Lower bound is the sum of the minumum fixed costs for the demands + the sum of the minimum distance for each demand
        # Note: any demand quantity will incur two routws, one for loading and one for unloading
        
        obj = obj - LB

    else:
        print(infeasibility)
   

    return obj

def heu_algorithm(prob_info, timelimit=60):
    """    
    기반: Rock-Solid Minimal Rehandling Algorithm
    개선: 
    1. 한 정거장만 이동하는 단기 수요를 특별 관리
    2. 단기 수요는 출입구 근처에 마지막에 선적
    3. LIFO 원칙 적용으로 재배치 최소화
    """
    
    def unloading_heuristic_optimized(p, node_allocations, T):
        """
        최적화된 하역 로직:
        - 단기 수요(이전 항구에서 선적된 차량)는 출입구와 가까운 순서로 먼저 하역
        - 장기 수요는 기존 로직대로 처리
        """
        # 현재 항구에서 하역해야 할 수요 식별
        K_unload = {idx: r for idx, ((o, d), r) in enumerate(K) if d == p}
        route_list = []
        
        # 단기 수요 식별 (이전 항구에서 선적된 차량)
        short_term_demands = {k for k in K_unload if K[k][0][0] == p-1}
        long_term_demands = {k for k in K_unload if k not in short_term_demands}
        
        
        
        # 작업 스택 초기화 - 단기 수요와 장기 수요 분리
        task_stack = []
        
        # 1. 단기 수요 처리 (출입구와 가까운 순서대로)
        for k in short_term_demands:
            nodes_with_demand = [n for n, dem_idx in enumerate(node_allocations) if dem_idx == k]
            # 출입구와 가까운 순서대로 정렬 (단기 수요는 출입구 가까이에 있어야 함)
            nodes_with_demand.sort(key=lambda n: distances_from_gate[n])
            for node in nodes_with_demand:
                task_stack.append({'type': 'UNLOAD', 'k': k, 'node': node, 'priority': 'HIGH'})
        
        # 2. 장기 수요 처리 (기존 로직과 동일)
        for k in long_term_demands:
            nodes_with_demand = [n for n, dem_idx in enumerate(node_allocations) if dem_idx == k]
            # 출입구에서 먼 순서대로 정렬 (장기 수요는 깊숙이 적재되어 있음)
            nodes_with_demand.sort(key=lambda n: distances_from_gate[n], reverse=True)
            for node in nodes_with_demand:
                task_stack.append({'type': 'UNLOAD', 'k': k, 'node': node, 'priority': 'NORMAL'})

        processed_tasks = set()
        
        # 작업 처리 - 높은 우선순위(단기 수요)부터 처리
        # 우선순위별로 정렬 - HIGH가 먼저 오도록
        task_stack.sort(key=lambda t: 0 if t['priority'] == 'HIGH' else 1)
        
        while task_stack:
            task = task_stack.pop(0)  # 큐처럼 앞에서부터 처리 (우선순위 유지)
            task_id = (task['type'], task['k'], task['node'])

            if task_id in processed_tasks or node_allocations[task['node']] != task['k']:
                continue

            path_to_gate = nx.shortest_path(T, source=task['node'], target=0)
            blockers = [n for n in path_to_gate[1:] if node_allocations[n] != -1]

            if not blockers:
                # 방해물이 없으면 작업 수행
                route_list.append((path_to_gate, task['k']))
                node_allocations[task['node']] = -1
                processed_tasks.add(task_id)
            else:
                # 방해물이 있으면, 원래 작업과 방해물 재배치 작업을 다시 스택에 추가
                task_stack.append(task)
                
                for bn in blockers:
                    blocker_k = node_allocations[bn]
                    blocker_task_id = ('REHANDLE', blocker_k, bn)
                    if blocker_task_id not in processed_tasks:
                        # 방해물 재배치 작업에도 우선순위 부여
                        blocker_priority = 'HIGH' if task['priority'] == 'HIGH' else 'NORMAL'
                        task_stack.append({'type': 'REHANDLE', 'k': blocker_k, 'node': bn, 'priority': blocker_priority})
                
                # 작업 스택 재정렬 - 우선순위 유지
                task_stack.sort(key=lambda t: 0 if t['priority'] == 'HIGH' else 1)

        # 최종 재배치 수요 목록 생성
        rehandling_demands = [k for r, k in route_list if r[-1] == 0 and k not in K_unload]
        
        return route_list, rehandling_demands

    def smart_loading_optimized(p, node_allocations, rehandling_demands, T):
        """
        최적화된 선적 로직:
        1. 단기 수요(다음 항구에서 하역)는 마지막에 선적
        2. 단기 수요는 출입구와 가까운 곳에 배치
        3. 동일 목적지 내에서 선적 순서와 위치 관계 최적화
        """
        K_load_new = {idx: r for idx, ((o, d), r) in enumerate(K) if o == p}
        
        # 모든 수요 수집
        all_demands_to_load = []
        for k, r in K_load_new.items():
            all_demands_to_load.extend([k] * r)
        all_demands_to_load.extend(rehandling_demands)

        route_list = []
        
        # 단기 수요와 장기 수요 분리
        short_term_demands = [k for k in all_demands_to_load if K[k][0][1] == p+1]
        long_term_demands = [k for k in all_demands_to_load if k not in short_term_demands]
        
        
        
        # 1. 먼저 장기 수요 처리 (목적지별로 그룹화)
        long_term_groups = defaultdict(list)
        for k in long_term_demands:
            dest = K[k][0][1]
            long_term_groups[dest].append(k)
        
        # 목적지 기준 정렬 (늦게 내릴수록 먼저 선적)
        sorted_destinations = sorted(long_term_groups.keys(), reverse=True)
        
        # 장기 수요 적재 위치 - 깊은 곳에 배치
        deep_nodes = [n for n, alloc in enumerate(node_allocations) if alloc == -1 and n != 0]
        deep_nodes.sort(key=lambda n: distances_from_gate[n], reverse=True)
        
        # 장기 수요 선적 실행
        node_index = 0
        
        for dest in sorted_destinations:
            vehicles = long_term_groups[dest]
            
            
            for vehicle_k in vehicles:
                placed = False
                
                # 가용 노드에서 적절한 위치 찾기 (깊은 곳부터)
                for i in range(node_index, len(deep_nodes)):
                    node = deep_nodes[i]
                    
                    # 이미 사용된 노드면 스킵
                    if node_allocations[node] != -1:
                        continue
                    
                    try:
                        path = nx.shortest_path(T, source=0, target=node)
                        
                        # 경로가 깨끗한지 확인
                        path_clear = True
                        for path_node in path[1:-1]:
                            if node_allocations[path_node] != -1:
                                path_clear = False
                                break
                        
                        if path_clear:
                            route_list.append((path, vehicle_k))
                            node_allocations[node] = vehicle_k
                            placed = True
                            
                            # 다음 차량은 다음 노드부터 검색 (연속 배치)
                            if i == node_index:
                                node_index += 1
                            break
                    except:
                        continue
                
                # 적절한 곳을 못 찾으면 아무 빈 곳에라도 배치 (안전망)
                if not placed:
                    for node in range(1, N):
                        if node_allocations[node] == -1:
                            try:
                                path = nx.shortest_path(T, source=0, target=node)
                                path_clear = True
                                for path_node in path[1:-1]:
                                    if node_allocations[path_node] != -1:
                                        path_clear = False
                                        break
                                
                                if path_clear:
                                    route_list.append((path, vehicle_k))
                                    node_allocations[node] = vehicle_k
                                    placed = True
                                    
                                    break
                            except:
                                continue
                
               
        
        # 2. 단기 수요 처리 - 출입구와 가까운 곳에 마지막에 선적
        # 남은 노드 중 출입구와 가까운 순서로 정렬
        shallow_nodes = [n for n, alloc in enumerate(node_allocations) if alloc == -1 and n != 0]
        shallow_nodes.sort(key=lambda n: distances_from_gate[n])  # 출입구와 가까운 순서대로
        
        
        
        # 단기 수요 중에서도 선적 순서 최적화:
        # 먼저 선적되는 차량은 더 안쪽에 배치 (출입구에서 더 먼 곳)
        for i, vehicle_k in enumerate(short_term_demands):
            placed = False
            
            # 출입구와 가까운 순서로 정렬된 노드 중, 인덱스에 맞는 위치 찾기
            # 인덱스가 작을수록(먼저 처리할수록) 더 안쪽에 배치
            target_index = len(short_term_demands) - i - 1  # 역순 인덱스
            
            if target_index < len(shallow_nodes):
                node = shallow_nodes[target_index]
                
                try:
                    path = nx.shortest_path(T, source=0, target=node)
                    
                    # 경로 검증
                    path_clear = True
                    for path_node in path[1:-1]:
                        if node_allocations[path_node] != -1:
                            path_clear = False
                            break
                    
                    if path_clear:
                        route_list.append((path, vehicle_k))
                        node_allocations[node] = vehicle_k
                        placed = True
                        
                        # 사용한 노드 제거
                        shallow_nodes.remove(node)
                except:
                    pass
            
            # 지정 위치에 배치 실패 시 다른 위치 시도
            if not placed:
                for node in shallow_nodes:
                    try:
                        path = nx.shortest_path(T, source=0, target=node)
                        path_clear = True
                        for path_node in path[1:-1]:
                            if node_allocations[path_node] != -1:
                                path_clear = False
                                break
                        
                        if path_clear:
                            route_list.append((path, vehicle_k))
                            node_allocations[node] = vehicle_k
                            placed = True
                            
                            # 사용한 노드 제거
                            shallow_nodes.remove(node)
                            break
                    except:
                        continue
            
            # 모든 시도 실패 시 아무 빈 노드에 배치
            if not placed:
                for node in range(1, N):
                    if node_allocations[node] == -1:
                        try:
                            path = nx.shortest_path(T, source=0, target=node)
                            path_clear = True
                            for path_node in path[1:-1]:
                                if node_allocations[path_node] != -1:
                                    path_clear = False
                                    break
                            
                            if path_clear:
                                route_list.append((path, vehicle_k))
                                node_allocations[node] = vehicle_k
                                placed = True
                                
                                break
                        except:
                            continue
            
            
                

        return route_list, node_allocations

    # 메인 알고리즘
    N, E, K, P, F = prob_info['N'], prob_info['E'], prob_info['K'], prob_info['P'], prob_info['F']
    
    
    
    # 그래프 구성 (MST 사용으로 단순화)
    G = nx.Graph()
    G.add_nodes_from(range(N))
    G.add_edges_from(set(tuple(sorted(e)) for e in E))
    
    T = nx.minimum_spanning_tree(G)
    distances_from_gate = nx.single_source_shortest_path_length(T, 0)

    # 상태 초기화
    node_allocations = np.ones(N, dtype=int) * -1
    solution = {p: [] for p in range(P)}

    # 각 항구별 처리
    for p in range(P):
        

        rehandling_demands = []
        
        # 최적화된 하역 로직
        if p > 0:
            route_list_unload, rehandling_demands = unloading_heuristic_optimized(p, node_allocations, T)
            solution[p].extend(route_list_unload)
            

        # 최적화된 선적 로직
        if p < P - 1:
            route_list_load, node_allocations = smart_loading_optimized(p, node_allocations, rehandling_demands, T)
            solution[p].extend(route_list_load)
            
            
            # 상태 확인
            occupied = np.sum(node_allocations != -1)
            

    
    return solution

if __name__ == "__main__":
    

    import json
    import os
    import sys
    import jsbeautifier


    def numpy_to_python(obj):
        if isinstance(obj, np.int64) or isinstance(obj, np.int32):
            return int(obj)  
        if isinstance(obj, np.float64) or isinstance(obj, np.float32):
            return float(obj)
        if isinstance(obj, np.ndarray):
            return obj.tolist()
        
        raise TypeError(f"Type {type(obj)} not serializable")
    
    
    
    if len(sys.argv) == 4:
        prob_name = sys.argv[1]
        prob_file = sys.argv[2]
        timelimit = int(sys.argv[3])

        with open(prob_file, 'r') as f:
            prob_info = json.load(f)

        exception = None
        solution = None

        try:

            alg_start_time = time.time()

            
            solution = algorithm(prob_info, timelimit)

            alg_end_time = time.time()


            checked_solution = util.check_feasibility(prob_info, solution)

            checked_solution['time'] = alg_end_time - alg_start_time
            checked_solution['timelimit_exception'] = (alg_end_time - alg_start_time) > timelimit + 2 
            checked_solution['exception'] = exception

            checked_solution['prob_name'] = prob_name
            checked_solution['prob_file'] = prob_file


            with open('results.json', 'w') as f:
                opts = jsbeautifier.default_options()
                opts.indent_size = 2
                f.write(jsbeautifier.beautify(json.dumps(checked_solution, default=numpy_to_python), opts))
                print(f'Results are saved as file results.json')
                
            sys.exit(0)

        except Exception as e:
            print(f"Exception: {repr(e)}")
            sys.exit(1)

    else:
        print("Usage: python myalgorithm.py <problem_name> <problem_file> <timelimit_in_seconds>")
        sys.exit(2)

