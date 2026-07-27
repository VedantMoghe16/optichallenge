#ifndef YJR_SOLVER_H
#define YJR_SOLVER_H

#include <stdlib.h>
#include <stdio.h>
#include <string.h>
#include <math.h>
#include <limits.h>
#include <sys/time.h> 
#include <vector>
#include <algorithm>
#include <gurobi_c++.h>


struct SolutionData {
    
    int* x_indices;  
    double* x_values;
    int x_count;
    
    
    int* l_indices;  
    double* l_values;
    int l_count;
    
    
    int* w_indices;  
    double* w_values;
    int w_count;
    
    
    int* y_indices;  
    double* y_values;
    int y_count;
};

extern "C" {
    SolutionData* solve_mip(int N, int P, int K_count, int F, int edge_count, 
                           int** K_data, int* sorted_nodes, int** edges, double timelimit,
                            int max_distance, int** dist_mtx, int max_columns, int* cum_arr);
    SolutionData* solve_mip2(int N, int P, int K_count, int F, int edge_count, 
                           int** K_data, int* sorted_nodes, int** edges, double timelimit,
                            int max_distance, int** dist_mtx, int max_columns, int* cum_arr,
                            double start_time);
    void free_solution_data(SolutionData* sol);
}













#endif