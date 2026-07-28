#include "yjr_solver.h"
#include <vector>
#include <algorithm>
#include <unordered_map>
#include <tuple>
#include <utility>
#include <cstring>
#include <iostream>

int find_distance_threshold(int* cumulative_array, int array_size, int k) {
    int* found = std::lower_bound(cumulative_array, 
                                  cumulative_array + array_size, 
                                  k);
    
    if (found != cumulative_array + array_size) {
        return found - cumulative_array;
    }
    return -1;
}

std::vector<double> compute_demand_max_congestion(
    int K_count, 
    const std::vector<std::vector<int>>& D_st,
    const std::vector<double>& port_congestion) {
    
    std::vector<double> demand_max_congestion(K_count);
    
    for(int r = 0; r < K_count; r++) {
        double max_cong = 0.0;
        
        
        for(int p = D_st[r][0]; p < D_st[r][1]; p++) {
            max_cong = std::max(max_cong, port_congestion[p]);
        }
        
        demand_max_congestion[r] = max_cong;
    }
    
    return demand_max_congestion;
}

std::vector<double> compute_port_congestion_simple(int P, int N,
                                                   const std::vector<int>& D_s,
                                                   const std::vector<int>& H_t,
                                                   const std::vector<int>& F_t) {
    std::vector<double> port_congestion(P);
    
    
    int available_nodes = N - 1;
    
    for(int p = 0; p < P; p++) {
        
        port_congestion[p] = (double)(F_t[p]) / available_nodes;
    }
    

    return port_congestion;
}



double get_wall_time() {
    struct timeval time;
    gettimeofday(&time, NULL);
    return (double)time.tv_sec + (double)time.tv_usec * .000001;
}


inline void hash_combine(size_t& seed, int val) {
    
    seed ^= std::hash<int>{}(val) + 0x9e3779b9 + (seed << 6) + (seed >> 2);
}

struct fast_tuple4_hash {
    size_t operator()(const std::tuple<int,int,int,int>& t) const {
        size_t seed = 0;
        hash_combine(seed, std::get<0>(t));
        hash_combine(seed, std::get<1>(t));
        hash_combine(seed, std::get<2>(t));
        hash_combine(seed, std::get<3>(t));
        return seed;
    }
};

struct fast_pair_hash {
    size_t operator()(const std::pair<int,int>& p) const {
        size_t seed = 0;
        hash_combine(seed, p.first);
        hash_combine(seed, p.second);
        return seed;
    }
};

struct fast_tuple3_hash {
    size_t operator()(const std::tuple<int,int,int>& t) const {
        size_t seed = 0;
        hash_combine(seed, std::get<0>(t));
        hash_combine(seed, std::get<1>(t));
        hash_combine(seed, std::get<2>(t));
        return seed;
    }
};

extern "C" {
SolutionData* solve_mip(
    int N, int P, int K_count, int F, int edge_count, 
    int** K_data, int* sorted_nodes, int** edges, double timelimit, int max_distance, int** dist_mtx, int max_columns, int* cum_arr
) {
    double start_time = get_wall_time();
    
    GRBEnv env = GRBEnv();
    GRBModel model = GRBModel(env);
    
    
    std::vector<std::vector<int>> D_p_ind(P);
    
    std::vector<int> D_p_ind_sizes(P, 0);
    for(int i = 0; i < K_count; i++) {
        D_p_ind_sizes[K_data[i][0]]++;
    }
    for(int p = 0; p < P; p++) {
        D_p_ind[p].reserve(D_p_ind_sizes[p]);
    }
    
    std::vector<std::vector<int>> D_st(K_count, std::vector<int>(2));
    std::vector<int> D_qt(K_count);
    std::vector<int> D_m(K_count);
    std::vector<int> D_s(P, 0);
    std::vector<int> H_t(P, 0);
    std::vector<int> sorted_pos(N);
    int max_dist = max_distance;
    int max_cols = max_columns;
    

    std::vector<int> F_t(P);
    for(int p=0;p<P;p++){
       F_t[p] = 0; 
    }
    
    
    for(int i = 0; i < K_count; i++) {
        int o = K_data[i][0];
        int d = K_data[i][1];
        int quantity = K_data[i][2];
        
        D_p_ind[o].push_back(i);
        D_st[i][0] = o;
        D_st[i][1] = d;
        D_qt[i] = quantity;
        D_m[i] = d - o + 1;
        D_s[o] += quantity;
        H_t[d] += quantity;
        for(int j=o;j<d;j++){
            F_t[j] += quantity;
        }
        
    }

    
    for(int j = 0; j < N; j++) {
        sorted_pos[sorted_nodes[j]] = j;
    }
    
    
    
    size_t estimated_x_keys = 0;
    for(int p = 0; p < P; p++) {
        for(int q = 0; q <= p; q++) {
            for(int r : D_p_ind[q]) {
                if(p >= D_st[r][0] && p <= D_st[r][1]) {
                    estimated_x_keys += (N-1);
                }
            }
        }
    }
    
    std::vector<std::tuple<int,int,int,int>> x_keys;
    x_keys.reserve(estimated_x_keys);

    
    std::vector<std::vector<int>> F_cnt(P, std::vector<int>(P, 0));
    
    for(int p=0;p<P;p++){
        for(int i = 0; i < K_count; i++) {
            int o = K_data[i][0];
            int d = K_data[i][1];
            int quantity = K_data[i][2];
            int dist = d-o; 
            if(p>=o && p<d){
                for(int k=dist;k<P;k++){
                
                    F_cnt[p][k] += quantity;
                }
            }
        }
        for(int k=0;k<P;k++){
            double tmp = (double)(N*F_cnt[p][k])/F_t[p];
            F_cnt[p][k] =(int)std::ceil(tmp);
        }

    }
    
    
    
    
    
    
    
    
    
    std::vector<int> F_ratio(P);
    std::vector<int> F_ratio_min(P);
    for(int p=0;p<P;p++){
        int tmp = 0;
        int tmp2 = 10000;
        for(int p2=1;p2<P;p2++){
            if(tmp < F_cnt[p2][p]) tmp = F_cnt[p2][p];
            if(tmp2 > F_cnt[p2][p] && F_cnt[p2][p]>0) tmp2 = F_cnt[p2][p];
        }
        F_ratio[p] = tmp;
        F_ratio_min[p] = tmp2;
    }
    
    
    
    
    
    
    const int threshold_90 = std::min(90, (int)(0.8*N));
    const int threshold_40 = (int)(N*0.4);
    const int threshold_30 = (int)(N*0.3);
    const int threshold_20 = (int)(N*0.2);
    const int p_90 = (int)std::ceil(P*0.9);
    const int p_80 = (int)std::ceil(P*0.8);
    const int p_70 = (int)std::ceil(P*0.7);
    const int p_60 = (int)std::ceil(P*0.6);
    const int p_50 = (int)std::ceil(P*0.5);
    const int p_30 = (int)std::ceil(P*0.3);
    const int p_20 = (int)std::ceil(P*0.2);

    std::vector<int> K_ratio_max(K_count);
    std::vector<int> K_ratio_min(K_count);
    int tmp = 0;
    int tmp2 = 10000;
    for(int i = 0; i < K_count; i++) {
        int o = K_data[i][0];
        int d = K_data[i][1];
        int quantity = K_data[i][2];
        int dist = d-o; 
        tmp = 0;
        tmp2 = 10000;
        for(int j=o;j<d+1;j++){
            if(tmp < F_cnt[j][dist]) tmp = F_cnt[j][dist];
            if(tmp2 > F_cnt[j][dist] && F_cnt[j][dist]>0) tmp2 = F_cnt[j][dist];
        }
        K_ratio_max[i] = tmp;
        K_ratio_min[i] = tmp2;


    }

    std::vector<double> port_congestion = compute_port_congestion_simple(P, N, D_s, H_t, F_t);
    std::vector<double> demand_max_congestion = compute_demand_max_congestion(K_count, D_st, port_congestion);
    

    
    
    for(int p = 0; p < P; p++) {
        for(int i = 1; i < N; i++) {
            int pos = sorted_pos[i];
            
            for(int q = 0; q <= p; q++) {
                for(int r : D_p_ind[q]) {
                    if(p >= D_st[r][0] && p <= D_st[r][1]) {
                        
                        int duration = D_st[r][1] - D_st[r][0];
                        bool skip = false;
                        int d = D_st[r][1];
                        int o = D_st[r][0];
           
                        
                        
                        double buff = 10.0;
                        if(duration > p_90) buff = 1.0;
                        else if(duration > p_80) buff = 1.0;
                        else if(duration > p_70) buff = 1.2;
                        else if(duration > p_60) buff = 1.5;
                        else if(duration > p_50) buff = 2.0;
                        else if(duration > p_30) buff = 3.0;
                        
                        if(N>150&&P>15){
                            buff = 1.2;
                            if(timelimit>150){
                                if(duration <= p_30) buff = 1.4;
                            }
                        }else if(N>150&&P>=10){
			    buff = 1.2;
			    if(duration<=p_50) buff = 1.5;		
			    if(timelimit>150){
                                if(duration <= p_30) buff = 1.6;
                            }	
			}
			if(N>300){
			    buff = 1.2;
			    if(duration<=p_50) buff = 1.3;		
			    if(timelimit>150){
                                if(duration <= p_30) buff = 1.4;
                            }	
			}
                      
                        int space = std::ceil(buff*K_ratio_max[r]);

                        
                        bool in_lst = false;
                        int boundary = find_distance_threshold(cum_arr, max_dist, std::min(space, N));
                        
    
                        if(boundary >= max_dist) boundary=max_dist-1;
                        if (boundary == -1) {
                            skip = true;
                        } else {
                            
                            for(int l = 1; l <= boundary && !in_lst; l++) {
                                
                                for(int idx = 0; idx < max_cols; idx++) {
                                    int node_ind = dist_mtx[l][idx];
                                    if (node_ind < 0) break;  
                                    if (node_ind == pos) {
                                        in_lst = true;
                                        break;
                                    }
                                }
                            }
                            if (!in_lst) {
                                skip = true;
                            }
                        }
                        
                        
      
                        
    
                        
                        
                        if(!skip) {
                            x_keys.emplace_back(p, i, q, r);
                        }
                    }
                }
            }
        }
    }
    
    
    const int x_size = x_keys.size();
    const int y_size = (P-2) * (N-1);
    const int z_size = (P-2) * (N-1);
    const int w_size = P * N;
    
    
    int l_count = 0;
    for(int e = 0; e < edge_count; e++) {
        if(edges[e][0] > 0) l_count++;
    }
    const int l_total = P * l_count;
    
    
    std::unordered_map<std::tuple<int,int,int,int>, GRBVar, fast_tuple4_hash> x;
    x.reserve(x_size);
    
    std::unordered_map<std::pair<int,int>, GRBVar, fast_pair_hash> y, z, w;
    y.reserve(y_size);
    z.reserve(z_size);
    w.reserve(w_size);
    
    std::unordered_map<std::tuple<int,int,int>, GRBVar, fast_tuple3_hash> l;
    l.reserve(l_total);
    
    
    const int total_vars = x_size + y_size + z_size + w_size + l_total;
    
    
    std::vector<double> lb(total_vars, 0.0);
    std::vector<double> ub(total_vars, 1.0);
    std::vector<double> obj(total_vars, 0.0);
    std::vector<char> vtype(total_vars, GRB_BINARY);
    
    int var_idx = 0;
    
    
    for(int i = 0; i < x_size; i++) {
        
        var_idx++;
    }
    
    
    for(int i = 0; i < y_size; i++) {
        
        var_idx++;
    }
    
    
    for(int i = 0; i < z_size; i++) {
        
        var_idx++;
    }
    
    
    for(int p = 0; p < P; p++) {
        for(int i = 0; i < N; i++) {
            
            if(p == 0 || p == P-1) {
                ub[var_idx] = 0.0;  
            }
            if(i>0) obj[var_idx] = 2*F;  
            var_idx++;
        }
    }
    
    
    for(int i = 0; i < l_total; i++) {
        ub[var_idx] = N-1;  
        obj[var_idx] = 1.0;  
        vtype[var_idx] = GRB_INTEGER;  
        var_idx++;
    }
    
    
    GRBVar* vars = model.addVars(lb.data(), ub.data(), obj.data(), vtype.data(), NULL, total_vars);
    
    
    var_idx = 0;
    
    
    for(const auto& key : x_keys) {
        x[key] = vars[var_idx++];
    }
    
    
    for(int p = 1; p < P-1; p++) {
        for(int i = 1; i < N; i++) {
            y[{p,i}] = vars[var_idx++];
        }
    }
    
    
    for(int p = 1; p < P-1; p++) {
        for(int i = 1; i < N; i++) {
            z[{p,i}] = vars[var_idx++];
        }
    }
    
    
    for(int p = 0; p < P; p++) {
        for(int i = 0; i < N; i++) {
            w[{p,i}] = vars[var_idx++];
        }
    }
    
    
    for(int p = 0; p < P; p++) {
        for(int e = 0; e < edge_count; e++) {
            if(edges[e][0] > 0) {
                l[{p, edges[e][0], edges[e][1]}] = vars[var_idx++];
            }
        }
    }
    
    model.update();
    
    
    
    for(auto& kv : x) {
        int p = std::get<0>(kv.first);
        int q = std::get<2>(kv.first);
        if(p == q) {
            
            
            
            kv.second.set(GRB_IntAttr_BranchPriority, 300);
        }
    }
    
    
    for(auto& kv : x) {
        int p = std::get<0>(kv.first);
        int r = std::get<3>(kv.first);
        int q = std::get<2>(kv.first);
        if(D_st[r][0] < p && p < D_st[r][1] && q == D_st[r][0]) {
            kv.second.set(GRB_IntAttr_BranchPriority, -50);
        }
    }
    
    
    for(auto& kv : y) {
        kv.second.set(GRB_IntAttr_BranchPriority, 5000);
    }
    
    
    for(auto& kv : z) {
        kv.second.set(GRB_IntAttr_BranchPriority, 900);
    }
    
    
    for(auto& kv : w) {
        kv.second.set(GRB_IntAttr_BranchPriority, 500);
    }
    
    
    for(auto& kv : l) {
        kv.second.set(GRB_IntAttr_BranchPriority, -10000);
    }
    
    model.update();
    
    
    
    
    std::unordered_map<std::tuple<int,int,int>, std::vector<int>, fast_tuple3_hash> x_keys_by_pqr;
    std::unordered_map<std::pair<int,int>, std::vector<std::pair<int,int>>, fast_pair_hash> x_keys_by_pi;
    
    for(const auto& key : x_keys) {
        int p = std::get<0>(key);
        int i = std::get<1>(key);
        int q = std::get<2>(key);
        int r = std::get<3>(key);
        
        
        x_keys_by_pqr[{p, q, r}].push_back(i);
        
        
        if(p < D_st[r][1]) {
            x_keys_by_pi[{p,i}].emplace_back(q, r);
        }
    }
    
    
    std::vector<GRBLinExpr> lhs_exprs;
    std::vector<char> senses;
    std::vector<double> rhs_vals;
    
    
    size_t estimated_constrs = x_keys_by_pqr.size() + x_keys_by_pi.size();
    lhs_exprs.reserve(estimated_constrs);
    senses.reserve(estimated_constrs);
    rhs_vals.reserve(estimated_constrs);
    
    
    for(int p = 0; p < P; p++) {
        for(int q = 0; q <= p; q++) {
            for(int r : D_p_ind[q]) {
                if(p >= D_st[r][0] && p <= D_st[r][1]) {
                    auto group_it = x_keys_by_pqr.find({p, q, r});
                    if(group_it != x_keys_by_pqr.end()) {
                        GRBLinExpr expr = 0;
                        for(int i : group_it->second) {
                            expr += x[{p, i, q, r}];
                        }
                        lhs_exprs.push_back(expr);
                        senses.push_back(GRB_EQUAL);
                        rhs_vals.push_back(D_qt[r]);
                    }
                }
            }
        }
    }
    
    
    for(const auto& kv : x_keys_by_pi) {
        GRBLinExpr expr = 0;
        for(const auto& qr : kv.second) {
            expr += x[{kv.first.first, kv.first.second, qr.first, qr.second}];
        }
        lhs_exprs.push_back(expr);
        senses.push_back(GRB_LESS_EQUAL);
        rhs_vals.push_back(1.0);
    }
    
    
    if(!lhs_exprs.empty()) {
        GRBConstr* constrs = model.addConstrs(lhs_exprs.data(), senses.data(), 
                                              rhs_vals.data(), NULL, lhs_exprs.size());
        delete[] constrs;
        
        
        lhs_exprs.clear();
        senses.clear();
        rhs_vals.clear();
    }
    
    
    for(const auto& kv : x) {
        int p = std::get<0>(kv.first);
        int i = std::get<1>(kv.first);
        int q = std::get<2>(kv.first);
        int r = std::get<3>(kv.first);
        
        if(p == q) {
            GRBLinExpr expr = 0;
            for(int p1 = D_st[r][0]; p1 <= D_st[r][1]; p1++) {
                auto it = x.find({p1,i,q,r});
                if(it != x.end()) {
                    expr += it->second;
                }
            }
            model.addConstr(expr == D_m[r] * kv.second);
        }
    }
    
    
    for(int p = 1; p < P-1; p++) {
        for(int i = 1; i < N; i++) {
            GRBLinExpr expr = 0;
            bool has_terms = false;
            
            for(int q = 0; q < p; q++) {
                for(int r : D_p_ind[q]) {
                    if(p >= D_st[r][0] && p < D_st[r][1]) {
                        auto it = x.find({p, i, q, r});
                        if(it != x.end()) {
                            expr += it->second;
                            has_terms = true;
                        }
                    }
                }
            }
            
            if(has_terms) {
                model.addGenConstrIndicator(y[{p,i}], 0, expr <= 0);
            }
        }
    }
    
    
    
    std::vector<std::vector<int>> edges_to(N);
    for(int e = 0; e < edge_count; e++) {
        if(edges[e][0] > 0) {
            edges_to[edges[e][1]].push_back(e);
        }
    }
    
    for(int p = 1; p < P-1; p++) {
        for(int i = 1; i < N; i++) {
            if(!edges_to[i].empty()) {
                GRBLinExpr expr = 0;
                for(int e : edges_to[i]) {
                    auto it = l.find({p, edges[e][0], edges[e][1]});
                    if(it != l.end()) {
                        expr += it->second;
                    }
                }
                if(expr.size() > 0) {
                    model.addConstr(expr <= (N-1) * z[{p,i}]);
                }
            }
        }
    }
    
    
    for(int p = 1; p < P-1; p++) {
        for(int i = 1; i < N; i++) {
            GRBVar vars[2] = {z[{p,i}], y[{p,i}]};
            model.addGenConstrAnd(w[{p,i}], vars, 2);
        }
    }
    
    
    std::vector<std::vector<int>> edges_from(N);
    for(int e = 0; e < edge_count; e++) {
        if(edges[e][0] > 0) {
            edges_from[edges[e][0]].push_back(e);
        }
    }
    
    
    std::vector<GRBLinExpr> outflow_lhs;
    std::vector<double> outflow_rhs;
    outflow_lhs.reserve(P * (N-1));
    outflow_rhs.reserve(P * (N-1));
    
    for(int p = 0; p < P; p++) {
        for(int i = 1; i < N; i++) {
            GRBLinExpr expr = 0;
            
            
            for(int e : edges_from[i]) {
                auto it = l.find({p, i, edges[e][1]});
                if(it != l.end()) {
                    expr += it->second;
                }
            }
            
            
            for(int e : edges_to[i]) {
                auto it = l.find({p, edges[e][0], i});
                if(it != l.end()) {
                    expr -= it->second;
                }
            }
            
            
            for(int r : D_p_ind[p]) {
                auto it = x.find({p, i, p, r});
                if(it != x.end()) {
                    expr -= it->second;
                }
            }
            
            
            for(int q = 0; q <= p; q++) {
                for(int r : D_p_ind[q]) {
                    if(p == D_st[r][1]) {
                        auto it = x.find({p, i, q, r});
                        if(it != x.end()) {
                            expr -= it->second;
                        }
                    }
                }
            }
            
            
            auto w_it = w.find({p,i});
            if(w_it != w.end()) {
                expr -= 2 * w_it->second;
            }
            
            if(expr.size() > 0) {
                outflow_lhs.push_back(expr);
                outflow_rhs.push_back(0.0);
            }
        }
    }
    
    
    if(!outflow_lhs.empty()) {
        std::vector<char> outflow_senses(outflow_lhs.size(), GRB_GREATER_EQUAL);
        GRBConstr* outflow_constrs = model.addConstrs(outflow_lhs.data(), 
                                                      outflow_senses.data(), 
                                                      outflow_rhs.data(), 
                                                      NULL, outflow_lhs.size());
        delete[] outflow_constrs;
    }
    
    
    
    
    
    
    
    
    
    double remaining_time = timelimit - (get_wall_time() - start_time) - 1.2;
    model.set(GRB_IntParam_OutputFlag, 0);
    model.set(GRB_DoubleParam_TimeLimit, std::max(1.0, remaining_time));
    model.set(GRB_IntParam_ScaleFlag, 3);
    model.set(GRB_DoubleParam_ObjScale, 0);
    
    model.set(GRB_IntParam_MIPFocus, 2);
    model.set(GRB_IntParam_Cuts, 0);
    model.set(GRB_IntParam_Method, 2);
    model.set(GRB_IntParam_Threads, 4);
    model.set(GRB_IntParam_Crossover, 0);
    
    model.set(GRB_DoubleParam_BarConvTol, 1e-6);
    model.set(GRB_IntParam_Symmetry, 2);
    model.set(GRB_IntParam_MinRelNodes, 0);
    
    
    
    if(N <= 100) {
        model.set(GRB_IntParam_SubMIPNodes, 200);
        model.set(GRB_IntParam_RINS, 2);
        model.set(GRB_DoubleParam_Heuristics, 0.7);
        model.set(GRB_IntParam_FlowCoverCuts, 1);
        model.set(GRB_IntParam_CoverCuts, 1);
        
        
        model.set(GRB_IntParam_CutPasses, 2);
        

        
    
        model.set(GRB_DoubleParam_NodeLimit, GRB_MAXINT);
    } else if(N <= 150) {
        model.set(GRB_IntParam_SubMIPNodes, 300);
        model.set(GRB_IntParam_RINS, 2);
        model.set(GRB_DoubleParam_Heuristics, 0.7);
        model.set(GRB_IntParam_FlowCoverCuts, 1);
        model.set(GRB_IntParam_CoverCuts, 1);
        
        
        model.set(GRB_IntParam_CutPasses, 2);
        

        
  
        
        
        model.set(GRB_DoubleParam_NodeLimit, GRB_MAXINT);
    } else {
        model.set(GRB_IntParam_SubMIPNodes, 500);
        model.set(GRB_IntParam_RINS, 2);
              
        
        model.set(GRB_DoubleParam_Heuristics, 1);
    	
	
         for(auto& kv : w) {
             int p = kv.first.first;
             int i = kv.first.second;
            if(p>0 && p<P-1 && i > 0) {
                 kv.second.set(GRB_DoubleAttr_Obj, 5.0 * F);  
             }
         }
        
	model.set(GRB_DoubleParam_NodeLimit, GRB_MAXINT);
    }
    model.update();
    model.optimize();
    
    
    SolutionData* solution = new SolutionData();
    
    if(model.get(GRB_IntAttr_Status) == GRB_OPTIMAL || 
       model.get(GRB_IntAttr_SolCount) > 0) {
        
        
        std::vector<int> x_ind;
        std::vector<double> x_val;
        x_ind.reserve(x.size() * 4);
        x_val.reserve(x.size());
        
        for(const auto& kv : x) {
            double val = kv.second.get(GRB_DoubleAttr_X);
            if(val > 0.5) {
                x_ind.push_back(std::get<0>(kv.first));
                x_ind.push_back(std::get<1>(kv.first));
                x_ind.push_back(std::get<2>(kv.first));
                x_ind.push_back(std::get<3>(kv.first));
                x_val.push_back(val);
            }
        }
        
        std::vector<int> l_ind;
        std::vector<double> l_val;
        l_ind.reserve(l.size() * 3);
        l_val.reserve(l.size());
        
        for(const auto& kv : l) {
            double val = kv.second.get(GRB_DoubleAttr_X);
            if(val > 0.4) {
                l_ind.push_back(std::get<0>(kv.first));
                l_ind.push_back(std::get<1>(kv.first));
                l_ind.push_back(std::get<2>(kv.first));
                l_val.push_back(val);
            }
        }
        
        std::vector<int> w_ind;
        std::vector<double> w_val;
        w_ind.reserve(w.size() * 2);
        w_val.reserve(w.size());
        
        for(const auto& kv : w) {
            double val = kv.second.get(GRB_DoubleAttr_X);
            if(val > 0.5) {
                w_ind.push_back(kv.first.first);
                w_ind.push_back(kv.first.second);
                w_val.push_back(val);
            }
        }
        
        std::vector<int> y_ind;
        std::vector<double> y_val;
        y_ind.reserve(y.size() * 2);
        y_val.reserve(y.size());
        
        for(const auto& kv : y) {
            double val = kv.second.get(GRB_DoubleAttr_X);
            if(val > 0.5) {
                y_ind.push_back(kv.first.first);
                y_ind.push_back(kv.first.second);
                y_val.push_back(val);
            }
        }
        
        
        solution->x_count = x_val.size();
        if(solution->x_count > 0) {
            solution->x_indices = new int[x_ind.size()];
            solution->x_values = new double[x_val.size()];
            std::memcpy(solution->x_indices, x_ind.data(), x_ind.size() * sizeof(int));
            std::memcpy(solution->x_values, x_val.data(), x_val.size() * sizeof(double));
        } else {
            solution->x_indices = nullptr;
            solution->x_values = nullptr;
        }
        
        solution->l_count = l_val.size();
        if(solution->l_count > 0) {
            solution->l_indices = new int[l_ind.size()];
            solution->l_values = new double[l_val.size()];
            std::memcpy(solution->l_indices, l_ind.data(), l_ind.size() * sizeof(int));
            std::memcpy(solution->l_values, l_val.data(), l_val.size() * sizeof(double));
        } else {
            solution->l_indices = nullptr;
            solution->l_values = nullptr;
        }
        
        solution->w_count = w_val.size();
        if(solution->w_count > 0) {
            solution->w_indices = new int[w_ind.size()];
            solution->w_values = new double[w_val.size()];
            std::memcpy(solution->w_indices, w_ind.data(), w_ind.size() * sizeof(int));
            std::memcpy(solution->w_values, w_val.data(), w_val.size() * sizeof(double));
        } else {
            solution->w_indices = nullptr;
            solution->w_values = nullptr;
        }
        
        solution->y_count = y_val.size();
        if(solution->y_count > 0) {
            solution->y_indices = new int[y_ind.size()];
            solution->y_values = new double[y_val.size()];
            std::memcpy(solution->y_indices, y_ind.data(), y_ind.size() * sizeof(int));
            std::memcpy(solution->y_values, y_val.data(), y_val.size() * sizeof(double));
        } else {
            solution->y_indices = nullptr;
            solution->y_values = nullptr;
        }
        
    } else {

        if(timelimit - (get_wall_time() - start_time) > 10){
	    delete[] vars;
            return solve_mip2(N, P, K_count, F, edge_count, K_data, sorted_nodes, edges, timelimit, max_dist, dist_mtx, max_cols, cum_arr, start_time); 
        }else{
            solution->x_count = 0;
            solution->x_indices = nullptr;
            solution->x_values = nullptr;
            solution->l_count = 0;
            solution->l_indices = nullptr;
            solution->l_values = nullptr;
            solution->w_count = 0;
            solution->w_indices = nullptr;
            solution->w_values = nullptr;
            solution->y_count = 0;
            solution->y_indices = nullptr;
            solution->y_values = nullptr;
        }
    }
    delete[] vars;
    return solution;
}

void free_solution_data(SolutionData* sol) {
    if(sol) {
        delete[] sol->x_indices;
        delete[] sol->x_values;
        delete[] sol->l_indices;
        delete[] sol->l_values;
        delete[] sol->w_indices;
        delete[] sol->w_values;
        delete[] sol->y_indices;
        delete[] sol->y_values;
        delete sol;
    }
}

// ㅠㅡㅠ
SolutionData* solve_mip2(
    int N, int P, int K_count, int F, int edge_count, 
    int** K_data, int* sorted_nodes, int** edges, double timelimit, int max_distance, int** dist_mtx, int max_columns, int* cum_arr, double start_time)
 {
    GRBEnv env = GRBEnv();
    GRBModel model = GRBModel(env);
    
    
    std::vector<std::vector<int>> D_p_ind(P);
    
    std::vector<int> D_p_ind_sizes(P, 0);
    for(int i = 0; i < K_count; i++) {
        D_p_ind_sizes[K_data[i][0]]++;
    }
    for(int p = 0; p < P; p++) {
        D_p_ind[p].reserve(D_p_ind_sizes[p]);
    }
    
    std::vector<std::vector<int>> D_st(K_count, std::vector<int>(2));
    std::vector<int> D_qt(K_count);
    std::vector<int> D_m(K_count);
    std::vector<int> D_s(P, 0);
    std::vector<int> H_t(P, 0);
    std::vector<int> sorted_pos(N);
    int max_dist = max_distance;
    int max_cols = max_columns;
    

    std::vector<int> F_t(P);
    for(int p=0;p<P;p++){
       F_t[p] = 0; 
    }
    
    
    for(int i = 0; i < K_count; i++) {
        int o = K_data[i][0];
        int d = K_data[i][1];
        int quantity = K_data[i][2];
        
        D_p_ind[o].push_back(i);
        D_st[i][0] = o;
        D_st[i][1] = d;
        D_qt[i] = quantity;
        D_m[i] = d - o + 1;
        D_s[o] += quantity;
        H_t[d] += quantity;
        for(int j=o;j<d;j++){
            F_t[j] += quantity;
        }
        
    }

    
    for(int j = 0; j < N; j++) {
        sorted_pos[sorted_nodes[j]] = j;
    }
    
    
    
    size_t estimated_x_keys = 0;
    for(int p = 0; p < P; p++) {
        for(int q = 0; q <= p; q++) {
            for(int r : D_p_ind[q]) {
                if(p >= D_st[r][0] && p <= D_st[r][1]) {
                    estimated_x_keys += (N-1);
                }
            }
        }
    }
    
    std::vector<std::tuple<int,int,int,int>> x_keys;
    x_keys.reserve(estimated_x_keys);

    
    std::vector<std::vector<int>> F_cnt(P, std::vector<int>(P, 0));
    
    for(int p=0;p<P;p++){
        for(int i = 0; i < K_count; i++) {
            int o = K_data[i][0];
            int d = K_data[i][1];
            int quantity = K_data[i][2];
            int dist = d-o; 
            if(p>=o && p<d){
                for(int k=dist;k<P;k++){
                
                    F_cnt[p][k] += quantity;
                }
            }
        }
        for(int k=0;k<P;k++){
            double tmp = (double)(N*F_cnt[p][k])/F_t[p];
            F_cnt[p][k] =(int)std::ceil(tmp);
        }

    }
    
    
    
    
    
    
    
    
    
    std::vector<int> F_ratio(P);
    std::vector<int> F_ratio_min(P);
    for(int p=0;p<P;p++){
        int tmp = 0;
        int tmp2 = 10000;
        for(int p2=1;p2<P;p2++){
            if(tmp < F_cnt[p2][p]) tmp = F_cnt[p2][p];
            if(tmp2 > F_cnt[p2][p] && F_cnt[p2][p]>0) tmp2 = F_cnt[p2][p];
        }
        F_ratio[p] = tmp;
        F_ratio_min[p] = tmp2;
    }
    
    
    
    
    
    
    const int threshold_90 = std::min(90, (int)(0.8*N));
    const int threshold_40 = (int)(N*0.4);
    const int threshold_30 = (int)(N*0.3);
    const int threshold_20 = (int)(N*0.2);
    const int p_90 = (int)std::ceil(P*0.9);
    const int p_80 = (int)std::ceil(P*0.8);
    const int p_70 = (int)std::ceil(P*0.7);
    const int p_60 = (int)std::ceil(P*0.6);
    const int p_50 = (int)std::ceil(P*0.5);
    const int p_30 = (int)std::ceil(P*0.3);
    const int p_20 = (int)std::ceil(P*0.2);

    std::vector<int> K_ratio_max(K_count);
    std::vector<int> K_ratio_min(K_count);
    int tmp = 0;
    int tmp2 = 10000;
    for(int i = 0; i < K_count; i++) {
        int o = K_data[i][0];
        int d = K_data[i][1];
        int quantity = K_data[i][2];
        int dist = d-o; 
        tmp = 0;
        tmp2 = 10000;
        for(int j=o;j<d+1;j++){
            if(tmp < F_cnt[j][dist]) tmp = F_cnt[j][dist];
            if(tmp2 > F_cnt[j][dist] && F_cnt[j][dist]>0) tmp2 = F_cnt[j][dist];
        }
        K_ratio_max[i] = tmp;
        K_ratio_min[i] = tmp2;


    }

    std::vector<double> port_congestion = compute_port_congestion_simple(P, N, D_s, H_t, F_t);
    std::vector<double> demand_max_congestion = compute_demand_max_congestion(K_count, D_st, port_congestion);
    

    
    
    for(int p = 0; p < P; p++) {
        for(int i = 1; i < N; i++) {
            int pos = sorted_pos[i];
            
            for(int q = 0; q <= p; q++) {
                for(int r : D_p_ind[q]) {
                    if(p >= D_st[r][0] && p <= D_st[r][1]) {
                        
                        int duration = D_st[r][1] - D_st[r][0];
                        bool skip = false;
                        int d = D_st[r][1];
                        int o = D_st[r][0];
           
                        
                        
                        double buff = 10.0;
                        if(duration > p_90) buff = 1.1;
                        else if(duration > p_80) buff = 1.1;
                        else if(duration > p_70) buff = 1.2;
                        else if(duration > p_60) buff = 1.5;
                        else if(duration > p_50) buff = 4.0;
                        else if(duration > p_30) buff = 5.0;

			if(N>150&&P>15){
                            buff = 1.2;
                            
                            if(duration <= p_30) buff = 1.5;
                            
                        }
                        
                        int space = std::ceil(buff*K_ratio_max[r]);

                        
                        bool in_lst = false;
                        int boundary = find_distance_threshold(cum_arr, max_dist, std::min(space, N));
                        
    
                        if(boundary >= max_dist) boundary=max_dist-1;
                        if (boundary == -1) {
                            skip = true;
                        } else {
                            
                            for(int l = 1; l <= boundary && !in_lst; l++) {
                                
                                for(int idx = 0; idx < max_cols; idx++) {
                                    int node_ind = dist_mtx[l][idx];
                                    if (node_ind < 0) break;  
                                    if (node_ind == pos) {
                                        in_lst = true;
                                        break;
                                    }
                                }
                            }
                            if (!in_lst) {
                                skip = true;
                            }
                        }
                        
                        
      
                        
    
                        
                        
                        if(!skip) {
                            x_keys.emplace_back(p, i, q, r);
                        }
                    }
                }
            }
        }
    }
    
    
    const int x_size = x_keys.size();
    const int y_size = (P-2) * (N-1);
    const int z_size = (P-2) * (N-1);
    const int w_size = P * N;
    
    
    int l_count = 0;
    for(int e = 0; e < edge_count; e++) {
        if(edges[e][0] > 0) l_count++;
    }
    const int l_total = P * l_count;
    
    
    std::unordered_map<std::tuple<int,int,int,int>, GRBVar, fast_tuple4_hash> x;
    x.reserve(x_size);
    
    std::unordered_map<std::pair<int,int>, GRBVar, fast_pair_hash> y, z, w;
    y.reserve(y_size);
    z.reserve(z_size);
    w.reserve(w_size);
    
    std::unordered_map<std::tuple<int,int,int>, GRBVar, fast_tuple3_hash> l;
    l.reserve(l_total);
    
    
    const int total_vars = x_size + y_size + z_size + w_size + l_total;
    
    
    std::vector<double> lb(total_vars, 0.0);
    std::vector<double> ub(total_vars, 1.0);
    std::vector<double> obj(total_vars, 0.0);
    std::vector<char> vtype(total_vars, GRB_BINARY);
    
    int var_idx = 0;
    
    
    for(int i = 0; i < x_size; i++) {
        
        var_idx++;
    }
    
    
    for(int i = 0; i < y_size; i++) {
        
        var_idx++;
    }
    
    
    for(int i = 0; i < z_size; i++) {
        
        var_idx++;
    }
    
    
    for(int p = 0; p < P; p++) {
        for(int i = 0; i < N; i++) {
            
            if(p == 0 || p == P-1) {
                ub[var_idx] = 0.0;  
            }
            if(i>0) obj[var_idx] = 2*F;  
            var_idx++;
        }
    }
    
    
    for(int i = 0; i < l_total; i++) {
        ub[var_idx] = N-1;  
        obj[var_idx] = 1.0;  
        vtype[var_idx] = GRB_INTEGER;  
        var_idx++;
    }
    
    
    GRBVar* vars = model.addVars(lb.data(), ub.data(), obj.data(), vtype.data(), NULL, total_vars);
    
    
    var_idx = 0;
    
    
    for(const auto& key : x_keys) {
        x[key] = vars[var_idx++];
    }
    
    
    for(int p = 1; p < P-1; p++) {
        for(int i = 1; i < N; i++) {
            y[{p,i}] = vars[var_idx++];
        }
    }
    
    
    for(int p = 1; p < P-1; p++) {
        for(int i = 1; i < N; i++) {
            z[{p,i}] = vars[var_idx++];
        }
    }
    
    
    for(int p = 0; p < P; p++) {
        for(int i = 0; i < N; i++) {
            w[{p,i}] = vars[var_idx++];
        }
    }
    
    
    for(int p = 0; p < P; p++) {
        for(int e = 0; e < edge_count; e++) {
            if(edges[e][0] > 0) {
                l[{p, edges[e][0], edges[e][1]}] = vars[var_idx++];
            }
        }
    }
    
    model.update();
    
    
    
    for(auto& kv : x) {
        int p = std::get<0>(kv.first);
        int q = std::get<2>(kv.first);
        if(p == q) {
            
            
            
            kv.second.set(GRB_IntAttr_BranchPriority, 300);
        }
    }
    
    
    for(auto& kv : x) {
        int p = std::get<0>(kv.first);
        int r = std::get<3>(kv.first);
        int q = std::get<2>(kv.first);
        if(D_st[r][0] < p && p < D_st[r][1] && q == D_st[r][0]) {
            kv.second.set(GRB_IntAttr_BranchPriority, -50);
        }
    }
    
    
    for(auto& kv : y) {
        kv.second.set(GRB_IntAttr_BranchPriority, 5000);
    }
    
    
    for(auto& kv : z) {
        kv.second.set(GRB_IntAttr_BranchPriority, 900);
    }
    
    
    for(auto& kv : w) {
        kv.second.set(GRB_IntAttr_BranchPriority, 500);
    }
    
    
    for(auto& kv : l) {
        kv.second.set(GRB_IntAttr_BranchPriority, -10000);
    }
    
    model.update();
    
    
    
    
    std::unordered_map<std::tuple<int,int,int>, std::vector<int>, fast_tuple3_hash> x_keys_by_pqr;
    std::unordered_map<std::pair<int,int>, std::vector<std::pair<int,int>>, fast_pair_hash> x_keys_by_pi;
    
    for(const auto& key : x_keys) {
        int p = std::get<0>(key);
        int i = std::get<1>(key);
        int q = std::get<2>(key);
        int r = std::get<3>(key);
        
        
        x_keys_by_pqr[{p, q, r}].push_back(i);
        
        
        if(p < D_st[r][1]) {
            x_keys_by_pi[{p,i}].emplace_back(q, r);
        }
    }
    
    
    std::vector<GRBLinExpr> lhs_exprs;
    std::vector<char> senses;
    std::vector<double> rhs_vals;
    
    
    size_t estimated_constrs = x_keys_by_pqr.size() + x_keys_by_pi.size();
    lhs_exprs.reserve(estimated_constrs);
    senses.reserve(estimated_constrs);
    rhs_vals.reserve(estimated_constrs);
    
    
    for(int p = 0; p < P; p++) {
        for(int q = 0; q <= p; q++) {
            for(int r : D_p_ind[q]) {
                if(p >= D_st[r][0] && p <= D_st[r][1]) {
                    auto group_it = x_keys_by_pqr.find({p, q, r});
                    if(group_it != x_keys_by_pqr.end()) {
                        GRBLinExpr expr = 0;
                        for(int i : group_it->second) {
                            expr += x[{p, i, q, r}];
                        }
                        lhs_exprs.push_back(expr);
                        senses.push_back(GRB_EQUAL);
                        rhs_vals.push_back(D_qt[r]);
                    }
                }
            }
        }
    }
    
    
    for(const auto& kv : x_keys_by_pi) {
        GRBLinExpr expr = 0;
        for(const auto& qr : kv.second) {
            expr += x[{kv.first.first, kv.first.second, qr.first, qr.second}];
        }
        lhs_exprs.push_back(expr);
        senses.push_back(GRB_LESS_EQUAL);
        rhs_vals.push_back(1.0);
    }
    
    
    if(!lhs_exprs.empty()) {
        GRBConstr* constrs = model.addConstrs(lhs_exprs.data(), senses.data(), 
                                              rhs_vals.data(), NULL, lhs_exprs.size());
        delete[] constrs;
        
        
        lhs_exprs.clear();
        senses.clear();
        rhs_vals.clear();
    }
    
    
    for(const auto& kv : x) {
        int p = std::get<0>(kv.first);
        int i = std::get<1>(kv.first);
        int q = std::get<2>(kv.first);
        int r = std::get<3>(kv.first);
        
        if(p == q) {
            GRBLinExpr expr = 0;
            for(int p1 = D_st[r][0]; p1 <= D_st[r][1]; p1++) {
                auto it = x.find({p1,i,q,r});
                if(it != x.end()) {
                    expr += it->second;
                }
            }
            model.addConstr(expr == D_m[r] * kv.second);
        }
    }
    
    
    for(int p = 1; p < P-1; p++) {
        for(int i = 1; i < N; i++) {
            GRBLinExpr expr = 0;
            bool has_terms = false;
            
            for(int q = 0; q < p; q++) {
                for(int r : D_p_ind[q]) {
                    if(p >= D_st[r][0] && p < D_st[r][1]) {
                        auto it = x.find({p, i, q, r});
                        if(it != x.end()) {
                            expr += it->second;
                            has_terms = true;
                        }
                    }
                }
            }
            
            if(has_terms) {
                model.addGenConstrIndicator(y[{p,i}], 0, expr <= 0);
            }
        }
    }
    
    
    
    std::vector<std::vector<int>> edges_to(N);
    for(int e = 0; e < edge_count; e++) {
        if(edges[e][0] > 0) {
            edges_to[edges[e][1]].push_back(e);
        }
    }
    
    for(int p = 1; p < P-1; p++) {
        for(int i = 1; i < N; i++) {
            if(!edges_to[i].empty()) {
                GRBLinExpr expr = 0;
                for(int e : edges_to[i]) {
                    auto it = l.find({p, edges[e][0], edges[e][1]});
                    if(it != l.end()) {
                        expr += it->second;
                    }
                }
                if(expr.size() > 0) {
                    model.addConstr(expr <= (N-1) * z[{p,i}]);
                }
            }
        }
    }
    
    
    for(int p = 1; p < P-1; p++) {
        for(int i = 1; i < N; i++) {
            GRBVar vars[2] = {z[{p,i}], y[{p,i}]};
            model.addGenConstrAnd(w[{p,i}], vars, 2);
        }
    }
    
    
    std::vector<std::vector<int>> edges_from(N);
    for(int e = 0; e < edge_count; e++) {
        if(edges[e][0] > 0) {
            edges_from[edges[e][0]].push_back(e);
        }
    }
    
    
    std::vector<GRBLinExpr> outflow_lhs;
    std::vector<double> outflow_rhs;
    outflow_lhs.reserve(P * (N-1));
    outflow_rhs.reserve(P * (N-1));
    
    for(int p = 0; p < P; p++) {
        for(int i = 1; i < N; i++) {
            GRBLinExpr expr = 0;
            
            
            for(int e : edges_from[i]) {
                auto it = l.find({p, i, edges[e][1]});
                if(it != l.end()) {
                    expr += it->second;
                }
            }
            
            
            for(int e : edges_to[i]) {
                auto it = l.find({p, edges[e][0], i});
                if(it != l.end()) {
                    expr -= it->second;
                }
            }
            
            
            for(int r : D_p_ind[p]) {
                auto it = x.find({p, i, p, r});
                if(it != x.end()) {
                    expr -= it->second;
                }
            }
            
            
            for(int q = 0; q <= p; q++) {
                for(int r : D_p_ind[q]) {
                    if(p == D_st[r][1]) {
                        auto it = x.find({p, i, q, r});
                        if(it != x.end()) {
                            expr -= it->second;
                        }
                    }
                }
            }
            
            
            auto w_it = w.find({p,i});
            if(w_it != w.end()) {
                expr -= 2 * w_it->second;
            }
            
            if(expr.size() > 0) {
                outflow_lhs.push_back(expr);
                outflow_rhs.push_back(0.0);
            }
        }
    }
    
    
    if(!outflow_lhs.empty()) {
        std::vector<char> outflow_senses(outflow_lhs.size(), GRB_GREATER_EQUAL);
        GRBConstr* outflow_constrs = model.addConstrs(outflow_lhs.data(), 
                                                      outflow_senses.data(), 
                                                      outflow_rhs.data(), 
                                                      NULL, outflow_lhs.size());
        delete[] outflow_constrs;
    }
    
    
    double remaining_time = timelimit - (get_wall_time() - start_time) - 1.2;
    model.set(GRB_IntParam_OutputFlag, 0);
    model.set(GRB_DoubleParam_TimeLimit, std::max(1.0, remaining_time));
    model.set(GRB_IntParam_ScaleFlag, 3);
    model.set(GRB_DoubleParam_ObjScale, 0);
    
    model.set(GRB_IntParam_MIPFocus, 2);
    model.set(GRB_IntParam_Cuts, 0);
    model.set(GRB_IntParam_Method, 2);
    model.set(GRB_IntParam_Threads, 4);
    model.set(GRB_IntParam_Crossover, 0);
    
    model.set(GRB_DoubleParam_BarConvTol, 1e-6);
    model.set(GRB_IntParam_Symmetry, 2);
    model.set(GRB_IntParam_MinRelNodes, 0);
    
    
    
    if(N <= 100) {
        model.set(GRB_IntParam_SubMIPNodes, 200);
        model.set(GRB_IntParam_RINS, 2);
        model.set(GRB_DoubleParam_Heuristics, 0.9);
      
        

        
    
        model.set(GRB_DoubleParam_NodeLimit, GRB_MAXINT);
    } else if(N <= 150) {
        model.set(GRB_IntParam_SubMIPNodes, 300);
        model.set(GRB_IntParam_RINS, 2);
        model.set(GRB_DoubleParam_Heuristics, 0.9);
        

        
  
        
        
        model.set(GRB_DoubleParam_NodeLimit, GRB_MAXINT);
    } else {
        model.set(GRB_IntParam_SubMIPNodes, 500);
        model.set(GRB_IntParam_RINS, 2);
              
        
        model.set(GRB_DoubleParam_Heuristics, 1);
    	
	
         for(auto& kv : w) {
             int p = kv.first.first;
             int i = kv.first.second;
            if(p>0 && p<P-1 && i > 0) {
                 kv.second.set(GRB_DoubleAttr_Obj, 5.0 * F);  
             }
         }
        
	model.set(GRB_DoubleParam_NodeLimit, GRB_MAXINT);
    }
    model.update();
    model.optimize();
    
    
    SolutionData* solution = new SolutionData();
    
    if(model.get(GRB_IntAttr_Status) == GRB_OPTIMAL || 
       model.get(GRB_IntAttr_SolCount) > 0) {
        
        
        std::vector<int> x_ind;
        std::vector<double> x_val;
        x_ind.reserve(x.size() * 4);
        x_val.reserve(x.size());
        
        for(const auto& kv : x) {
            double val = kv.second.get(GRB_DoubleAttr_X);
            if(val > 0.5) {
                x_ind.push_back(std::get<0>(kv.first));
                x_ind.push_back(std::get<1>(kv.first));
                x_ind.push_back(std::get<2>(kv.first));
                x_ind.push_back(std::get<3>(kv.first));
                x_val.push_back(val);
            }
        }
        
        std::vector<int> l_ind;
        std::vector<double> l_val;
        l_ind.reserve(l.size() * 3);
        l_val.reserve(l.size());
        
        for(const auto& kv : l) {
            double val = kv.second.get(GRB_DoubleAttr_X);
            if(val > 0.4) {
                l_ind.push_back(std::get<0>(kv.first));
                l_ind.push_back(std::get<1>(kv.first));
                l_ind.push_back(std::get<2>(kv.first));
                l_val.push_back(val);
            }
        }
        
        std::vector<int> w_ind;
        std::vector<double> w_val;
        w_ind.reserve(w.size() * 2);
        w_val.reserve(w.size());
        
        for(const auto& kv : w) {
            double val = kv.second.get(GRB_DoubleAttr_X);
            if(val > 0.5) {
                w_ind.push_back(kv.first.first);
                w_ind.push_back(kv.first.second);
                w_val.push_back(val);
            }
        }
        
        std::vector<int> y_ind;
        std::vector<double> y_val;
        y_ind.reserve(y.size() * 2);
        y_val.reserve(y.size());
        
        for(const auto& kv : y) {
            double val = kv.second.get(GRB_DoubleAttr_X);
            if(val > 0.5) {
                y_ind.push_back(kv.first.first);
                y_ind.push_back(kv.first.second);
                y_val.push_back(val);
            }
        }
        
        
        solution->x_count = x_val.size();
        if(solution->x_count > 0) {
            solution->x_indices = new int[x_ind.size()];
            solution->x_values = new double[x_val.size()];
            std::memcpy(solution->x_indices, x_ind.data(), x_ind.size() * sizeof(int));
            std::memcpy(solution->x_values, x_val.data(), x_val.size() * sizeof(double));
        } else {
            solution->x_indices = nullptr;
            solution->x_values = nullptr;
        }
        
        solution->l_count = l_val.size();
        if(solution->l_count > 0) {
            solution->l_indices = new int[l_ind.size()];
            solution->l_values = new double[l_val.size()];
            std::memcpy(solution->l_indices, l_ind.data(), l_ind.size() * sizeof(int));
            std::memcpy(solution->l_values, l_val.data(), l_val.size() * sizeof(double));
        } else {
            solution->l_indices = nullptr;
            solution->l_values = nullptr;
        }
        
        solution->w_count = w_val.size();
        if(solution->w_count > 0) {
            solution->w_indices = new int[w_ind.size()];
            solution->w_values = new double[w_val.size()];
            std::memcpy(solution->w_indices, w_ind.data(), w_ind.size() * sizeof(int));
            std::memcpy(solution->w_values, w_val.data(), w_val.size() * sizeof(double));
        } else {
            solution->w_indices = nullptr;
            solution->w_values = nullptr;
        }
        
        solution->y_count = y_val.size();
        if(solution->y_count > 0) {
            solution->y_indices = new int[y_ind.size()];
            solution->y_values = new double[y_val.size()];
            std::memcpy(solution->y_indices, y_ind.data(), y_ind.size() * sizeof(int));
            std::memcpy(solution->y_values, y_val.data(), y_val.size() * sizeof(double));
        } else {
            solution->y_indices = nullptr;
            solution->y_values = nullptr;
        }
    } else {
        solution->x_count = 0;
        solution->x_indices = nullptr;
        solution->x_values = nullptr;
        solution->l_count = 0;
        solution->l_indices = nullptr;
        solution->l_values = nullptr;
        solution->w_count = 0;
        solution->w_indices = nullptr;
        solution->w_values = nullptr;
        solution->y_count = 0;
        solution->y_indices = nullptr;
        solution->y_values = nullptr;
    }
    delete[] vars;
    return solution;
}

} 