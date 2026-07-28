import json, sys
sys.path.insert(0, '/Users/anantasati/Downloads/optichallenge/submission/ogc_final_candidate')
import myalgorithm

if __name__ == "__main__":
    prob = json.load(open('/Users/anantasati/Downloads/optichallenge/train/prob_38.json'))
    sol = myalgorithm.algorithm(prob, 60.0)
    with open('/Users/anantasati/Downloads/optichallenge/experiments/results/final_mp_robustness_abs/kill_worker_sol.json', "w") as f:
        json.dump(sol, f)
