import util
import time
import json
import math
import numpy as np
import networkx as nx
import gurobipy as gp
from gurobipy import GRB

def path_backtracking(previous_nodes, start, target, reverse=False):
    path = []
    current_node = target

    while current_node != start:
        path.append(current_node)
        predecessors_list = previous_nodes[current_node]
        current_node = predecessors_list[0] # Take the first predecessor
        
    path.append(start)
    if not reverse:
        path.reverse()

    return path

def algorithm(prob_info, timelimit=60):
    model_gen_start_time = time.time()
    
    # Get parameters from the prob_info dictionary
    num_all_nodes = prob_info['N']  # nodes
    edges = prob_info['E']  # edges
    demands_info = prob_info['K']  # demands
    num_ports = prob_info['P']  # ports
    fixed_cost = prob_info['F']
    
    # === Data Preparation ===
    G = nx.Graph()
    G.add_nodes_from(range(num_all_nodes))
    G.add_edges_from(edges)

    parking_nodes = range(1, num_all_nodes) # All nodes except 0
    all_nodes = range(num_all_nodes)
    ports = range(num_ports)
    unloading_ports = range(1, num_ports) # Ports from 1 to P-1 (unloading at destination)
    loading_ports = range(num_ports - 1)  # Ports from 0 to P-2 (loading at origin)
    num_demands = len(demands_info)
    demands = range(num_demands)
    
    num_nodes = num_all_nodes-1
    num_unloading_ports = num_ports - 1
    num_loading_ports = num_ports - 1

    # Use NumPy array for the data structure
    demand_count_arr = np.empty(num_demands, dtype=np.int32)
    loading_port_arr = np.empty(num_demands, dtype=np.int32)
    unloading_port_arr = np.empty(num_demands, dtype=np.int32)
    
    loading_time_occupying_demands = np.array([[origin+1 <= p and p<destin for (origin, destin), _ in demands_info] for p in ports], dtype=bool)
    # unloading_time_occupying_demands = np.copy(loading_time_occupying_demands)
    loading_demands = np.zeros((num_ports, num_demands), dtype=bool)
    unloading_demands = np.zeros((num_ports, num_demands), dtype=bool)
    
    for idx, row in enumerate(demands_info):    
        # unloading_time_occupying_demands[row[0][1], idx] = True
        loading_demands[row[0][0], idx] = True
        unloading_demands[row[0][1], idx] = True
        loading_port_arr[idx] = row[0][0]
        unloading_port_arr[idx] = row[0][1]
        demand_count_arr[idx] = row[1]

    # Pre-calculate distances from Node 0 for the objective function
    predecessors_from_0, distances_from_0 = nx.predecessor(G, 0, return_seen=True)
    
    # === Gurobi Model Formulation ===
    model = gp.Model("RoRo")
    
    # --- Decision Variables ---
    var_gen_start_time = time.time()
    
    # Create NumPy arrays of Gurobi variables
    is_stowed = np.array([[model.addVar(vtype=GRB.BINARY, name=f'is_stowed_d{d}_n{n}') for n in all_nodes] for d in demands])
    is_reachable = np.array([[model.addVar(vtype=GRB.BINARY, name=f'is_reachable_p{p}_n{n}') for n in all_nodes] for p in ports])
    is_rehandled = np.array([[model.addVar(vtype=GRB.BINARY, name=f'is_rehandled_p{p}_n{n}') for n in all_nodes] for p in ports])
    
    # --- Constraints ---
    con_gen_start_time = time.time()
    
    # 1. Stowage Node Selection: Each vehicle must be stowed at exactly one parking node.
    model.addConstrs((gp.quicksum(is_stowed[d, n] for n in parking_nodes) == demand_count_arr[d] for d in demands), name="stowage_node_selection")
    
    
    # 2. Node Blocking Constraints
    model.addConstrs((gp.quicksum(is_stowed[d, n] for d in demands if loading_time_occupying_demands[p, d]) + is_reachable[p, n] <= 1 + is_rehandled[p, n]
                      for p in unloading_ports for n in parking_nodes), name="node_blocking")
    
    # 3. Reachability Constraints (Path Formation)
    model.addConstrs((is_reachable[p, n] <= gp.quicksum(is_reachable[p, n_prime] for n_prime in predecessors_from_0[n])
                      for p in ports for n in parking_nodes
                      if n in predecessors_from_0 and predecessors_from_0[n]), name="reachability")
    
    # 5. Stowage Node Must Be Reachable for Vehicle's Operation
    # model.addConstrs((is_stowed[d, n] <= is_reachable[unloading_port_arr[d], n] for d in demands for n in parking_nodes
    #                   ), name="reachable_to_unload")
    
    # model.addConstrs((is_stowed[d, n] <= is_reachable[loading_port_arr[d], n] for d in demands for n in parking_nodes
    #                   ), name="reachable_to_load")
    
    # 6. Loading/unloading Node Capacity
    
    model.addConstrs((gp.quicksum(is_stowed[d, n] for d in demands if unloading_demands[p, d]) + is_rehandled[p, n] <= is_reachable[p, n]
                      for n in parking_nodes for p in loading_ports), name="strengthened_unload_all_different")
    
    # model.addConstrs((gp.quicksum(is_stowed[d, n] for d in demands if loading_demands[p, d]) + is_rehandled[p, n] <= 1
    #                   for n in parking_nodes for p in loading_ports), name="load_all_different")
    
    model.addConstrs((gp.quicksum(is_stowed[d, n] for d in demands if loading_demands[p, d]) + is_rehandled[p, n] <= is_reachable[p, n]
                      for n in parking_nodes for p in loading_ports), name="strengthened_load_all_different")
    
    # --- Objective Function: Minimize Total Cost ---
    
    model.setObjective(gp.quicksum((fixed_cost + distances_from_0[n]) * (gp.quicksum(is_stowed[d, n] for d in demands) + gp.quicksum(is_rehandled[p, n] for p in ports)) for n in parking_nodes), GRB.MINIMIZE)
    
    # True objective cost
    # model.setObjective(2*(gp.quicksum((fixed_cost + distances_from_0[n]) * is_stowed[d, n] for d in demands for n in parking_nodes)+
    #                    gp.quicksum((fixed_cost + distances_from_0[n]) * is_rehandled[p, n] for p in ports for n in parking_nodes)) 
    #                    - prob_info['LB'],
    #                    GRB.MINIMIZE)
    
    # --- Solver Settings ---
    elapsed_time_model_gen = time.time() - model_gen_start_time
    model_time_limit = max(0, timelimit - elapsed_time_model_gen - 1)
    model.setParam('TimeLimit', model_time_limit)
    model.setParam('NoRelHeurWork', model_time_limit*3)
    model.setParam('OutputFlag', 0)

    # --- Solve the Model ---
    model.optimize()
    
    # --- Extract and Format Solution ---
    solution = {p: [] for p in ports}
    avail_nodes = np.ones(num_all_nodes, dtype=bool)
    
    if model.Status in [GRB.OPTIMAL, GRB.TIME_LIMIT]:
        # Efficiently retrieve solutions using .X attribute of Gurobi variables
        # This creates a NumPy array of the solution values
        stowage_nodes_matrix = np.array([[math.isclose(is_stowed[d, n].X, 1, abs_tol=1e-5) for n in all_nodes] for d in demands], dtype=bool)
        rehandled_nodes_matrix = np.array([[math.isclose(is_rehandled[p, n].X, 1, abs_tol=1e-5) for n in all_nodes] for p in ports], dtype=bool)
        
        # --- Path Reconstruction for each Port ---
        for curr_port in ports: 
            # 1. Unloading
            rehandled_nodes = rehandled_nodes_matrix[curr_port]
            curr_unloading_nodes = unloading_demands[curr_port] @ stowage_nodes_matrix
            unloading_nodes = np.logical_or(rehandled_nodes, curr_unloading_nodes)
            avail_nodes[unloading_nodes] = True
    
            unloading_pred, unloading_dist = nx.predecessor(G.subgraph(np.array(np.nonzero(avail_nodes)).squeeze().tolist()), 0, return_seen=True)
    
            unloading_nodes_arr = np.array(np.nonzero(unloading_nodes)).reshape(-1)
            unloading_nodes_dist_arr = np.array([unloading_dist[n] for n in unloading_nodes_arr])
    
            ordered_unloading_nodes_arr = unloading_nodes_arr[np.argsort(unloading_nodes_dist_arr)]
            for unloading_node in ordered_unloading_nodes_arr:
                path_to_unload = path_backtracking(unloading_pred, 0, int(unloading_node), reverse=True)
                if path_to_unload:
                    if curr_unloading_nodes[unloading_node]:                
                        demand = np.argmax(np.logical_and(unloading_demands[curr_port], stowage_nodes_matrix[:,unloading_node]))
                    elif rehandled_nodes[unloading_node]:
                        demand = np.argmax(np.logical_and(loading_time_occupying_demands[curr_port], stowage_nodes_matrix[:,unloading_node]))  
                
                solution[curr_port].append([path_to_unload, demand])          
            
            # 2. Loading
            curr_loading_nodes = loading_demands[curr_port] @ stowage_nodes_matrix
            loading_nodes = np.logical_or(rehandled_nodes, curr_loading_nodes)
    
            loading_pred, loading_dist = nx.predecessor(G.subgraph(np.array(np.nonzero(avail_nodes)).squeeze().tolist()), 0, return_seen=True)
    
            loading_nodes_arr = np.array(np.nonzero(loading_nodes), dtype=int).reshape(-1)
            loading_nodes_dist_arr = np.array([loading_dist[n] for n in loading_nodes_arr])
    
            ordered_loading_nodes_arr = loading_nodes_arr[np.argsort(loading_nodes_dist_arr)[::-1]]
            for loading_node in ordered_loading_nodes_arr:
                path_to_load = path_backtracking(loading_pred, 0, int(loading_node), reverse=False)  
                if path_to_load:
                    if curr_loading_nodes[loading_node]:
                        demand = np.argmax(np.logical_and(loading_demands[curr_port], stowage_nodes_matrix[:,loading_node]))  
                    elif rehandled_nodes[loading_node]:
                        demand = np.argmax(np.logical_and(loading_time_occupying_demands[curr_port], stowage_nodes_matrix[:,loading_node]))  
          
                solution[curr_port].append([path_to_load, demand])  
                avail_nodes[loading_node] = False
    else:
        pass # No exception handling for now
    
    return solution

if __name__ == "__main__":
    # You can run this file to test your algorithm from terminal.

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
    
    
    # Arguments list should be problem_name, problem_file, timelimit (in seconds)
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

            # Run algorithm!
            solution = algorithm(prob_info, timelimit)

            alg_end_time = time.time()


            checked_solution = util.check_feasibility(prob_info, solution)

            checked_solution['time'] = alg_end_time - alg_start_time
            checked_solution['timelimit_exception'] = (alg_end_time - alg_start_time) > timelimit + 2 # allowing additional 2 second!
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