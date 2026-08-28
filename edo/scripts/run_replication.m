% run_replication.m -- runs calib_smoother against the paper-exact
% replication dataset (models/linearized_replication.mod, generated from
% linearized.mod with only the datafile path changed) and exports it
% separately from the current-analysis default pipeline. This reproduces
% the original Kiley (2013)/EDO proof-of-concept -- a validation
% reference point, not the regular pipeline. Run from within models/.

data_file = '../data/observables_replication.csv';
output_csv = 'output_gap_replication.csv';
manifest_json = 'output_gap_replication_manifest.json';

dynare linearized_replication.mod noclearall;
run('../scripts/export_results.m');
