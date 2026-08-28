% run_replication.m -- runs calib_smoother-equivalent estimation against
% the paper-exact replication dataset (1960:Q1-2017:Q4, matching "My
% estimation sample spans from 1960:Q1 to 2017:Q4" in the published
% paper) and exports it separately from the current-analysis pipeline.
% Run from within models/.

data_file = '../data/observables_replication.csv';
output_csv = 'rstar_replication.csv';
manifest_json = 'rstar_replication_manifest.json';

dynare rg_base_final_replication.mod noclearall;
run('../scripts/export_results.m');
