import json, sys
sys.path.insert(0, 'submission/ogc_final_candidate')
import myalgorithm

if __name__ == "__main__":
    prob = json.load(open('train 2/prob_20.json'))
    sol = myalgorithm.algorithm(prob, 60.0)
    with open('experiments/results/final_mp_robustness/kill_worker_sol.json', "w") as f:
        json.dump(sol, f)
