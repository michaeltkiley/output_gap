% export_results.m
% Run AFTER `dynare rg_base_final.mod noclearall` (from within models/) --
% pulls r*, the output gap, the unemployment gap, and trend growth out of
% oo_ and writes plain CSV/JSON for the website.
%
% Variable-naming note (easy to get backwards, and I did the first time):
% `yU` is the OUTPUT gap -- it drives yobs = t1 + yU. `uU` is the
% UNEMPLOYMENT gap, derived from yU via Okun's law (uU = uy*distributed_lag(yU))
% and feeding lur = uU + t3. Both are exported, clearly labeled.
%
% r* is NOT oo_.SmoothedVariables.tr directly -- tr is a pure random walk
% pinned near 0 at the start of the sample (see build_observables.py); the
% actual r* series is tr + mean(rff - dp), i.e. tr plus the average
% REALIZED real fed funds rate. For the current-analysis (live page)
% output, that average is computed over a FIXED window, 1960:Q1-2007:Q4
% (pre-financial-crisis/pre-ZLB -- an explicit user choice, made
% 2026-08-28, replacing an earlier version that averaged over the full
% expanding current-analysis sample instead, which let the 2008-15/
% 2020-21 near-zero-rate years pull the constant down as more data
% accumulated). Replication mode is a deliberate exception -- see the
% "is_replication" branch below. Both one-sided (filtered/real-time,
% oo_.UpdatedVariables) and two-sided (smoothed, oo_.SmoothedVariables)
% estimates are exported.
%
% Uncertainty: +-2 std dev bands for the two-sided output gap and r*,
% from oo_.Smoother.State_uncertainty (the model's `smoothed_state_uncertainty`
% option -- a standard Kalman/RTS smoother covariance, available at the
% posterior mode with no MCMC needed). This is filtering/smoothing
% uncertainty CONDITIONAL ON the point-estimated parameters -- it does not
% include parameter uncertainty (see rstar/README.md "Uncertainty" for why
% that's a deliberately separate, harder question). r*'s variance equals
% tr's directly, since r* = tr + a constant. No band exists for the
% one-sided/filtered series -- State_uncertainty is smoothed-only.
%
% Optionally set `data_file` and `output_csv` in the workspace before
% calling this (e.g. for --replication); otherwise defaults to the
% standard pipeline paths.

if ~exist('data_file', 'var')
    data_file = '../data/observables.csv';
end
if ~exist('output_csv', 'var')
    output_csv = 'rstar.csv';
end
if ~exist('manifest_json', 'var')
    manifest_json = 'manifest.json';
end

output_dir = '../outputs';
if ~exist(output_dir, 'dir')
    mkdir(output_dir);
end

% Re-read dates and the rff/dp columns needed for the r* reconstruction --
% oo_.SmoothedVariables/.UpdatedVariables are shorter than the full data
% sample by `presample` (4 obs dropped at the start), so align from the
% END of both series, which share the same last date.
fid = fopen(data_file);
% CollapseDelimiters=false is required: Octave's strsplit collapses
% consecutive delimiters by default, which silently shifts every column
% after an empty field (ptr is frequently empty in the Hoey/BZW era) --
% found by comparing against an independent Python parse of the same
% file, which doesn't have this behavior.
header = strsplit(fgetl(fid), ',', 'CollapseDelimiters', false);
rff_col = find(strcmp(header, 'rff'));
dp_col = find(strcmp(header, 'dp'));
dates = {}; rff_all = []; dp_all = [];
line = fgetl(fid);
while ischar(line)
    parts = strsplit(line, ',', 'CollapseDelimiters', false);
    dates{end+1} = parts{1}; %#ok<AGROW>
    rff_all(end+1) = str2double(parts{rff_col}); %#ok<AGROW>
    dp_all(end+1) = str2double(parts{dp_col}); %#ok<AGROW>
    line = fgetl(fid);
end
fclose(fid);

% The constant added to tr to form r*: mean(rff - dp) over a FIXED window
% for the current-analysis (live page) output only -- see the note at the
% top of this file. Replication mode instead uses the full available
% sample (every row in observables_replication.csv), closely matching
% the original paper's own real-time convention (mean over ~1965:Q1
% through the run date, i.e. "as much history as exists at the time") --
% switching
% replication to the fixed pre-crisis window too would break the
% paper-verification check's fidelity to the paper's own published
% numbers, which is the whole point of replication mode.
is_replication = strcmp(output_csv, 'rstar_replication.csv');
if is_replication
    RSTAR_CONST_SAMPLE_START = dates{1};
    RSTAR_CONST_SAMPLE_END = dates{end};
    in_const_sample = true(1, numel(dates));
else
    % CollapseDelimiters-safe parse above guarantees dates{i} is a plain
    % "YYYYQ#" string.
    RSTAR_CONST_SAMPLE_START = '1960Q1';
    RSTAR_CONST_SAMPLE_END = '2007Q4';
    date_to_num = @(s) str2double(s(1:4)) * 10 + str2double(s(6));
    const_start_num = date_to_num(RSTAR_CONST_SAMPLE_START);
    const_end_num = date_to_num(RSTAR_CONST_SAMPLE_END);
    in_const_sample = false(1, numel(dates));
    for i = 1:numel(dates)
        in_const_sample(i) = date_to_num(dates{i}) >= const_start_num && date_to_num(dates{i}) <= const_end_num;
    end
end
% Explicit NaN-safe mean, not nanmean: it's either undefined in this
% Octave/package combination or resolves to an unrelated Dynare-internal
% function of the same name -- confirmed unreliable by direct testing,
% not worth trusting either way.
rff_valid = rff_all(in_const_sample & ~isnan(rff_all));
dp_valid = dp_all(in_const_sample & ~isnan(dp_all));
if isempty(rff_valid) || isempty(dp_valid)
    error('export_results: no non-NaN rff/dp observations in %s:%s -- check the constant window', ...
        RSTAR_CONST_SAMPLE_START, RSTAR_CONST_SAMPLE_END);
end
rff_mean = sum(rff_valid) / numel(rff_valid);
dp_mean = sum(dp_valid) / numel(dp_valid);

tr_smoothed = oo_.SmoothedVariables.tr(:);
tr_filtered = oo_.UpdatedVariables.tr(:);
yU_smoothed = oo_.SmoothedVariables.yU(:);   % output gap
yU_filtered = oo_.UpdatedVariables.yU(:);
uU_smoothed = oo_.SmoothedVariables.uU(:);   % unemployment gap
uU_filtered = oo_.UpdatedVariables.uU(:);
tg_smoothed = oo_.SmoothedVariables.tg(:);
tg_filtered = oo_.UpdatedVariables.tg(:);
n_out = numel(tr_smoothed);
n_full = numel(dates);
if n_out > n_full
    error('export_results: %d smoothed observations but only %d dates -- sample mismatch', n_out, n_full);
end
dates = dates(end - n_out + 1:end);

rstar_2side = tr_smoothed + rff_mean - dp_mean;
rstar_1side = tr_filtered + rff_mean - dp_mean;

% +-2 std dev bands (smoothed/two-sided only; conditional on the mode's
% point-estimated parameters -- see the note above this section).
BAND_WIDTH_SD = 2;
have_uncertainty = isfield(oo_, 'Smoother') && isfield(oo_.Smoother, 'State_uncertainty');
if have_uncertainty
    yU_idx = strmatch('yU', M_.endo_names, 'exact');
    tr_idx = strmatch('tr', M_.endo_names, 'exact');
    su = oo_.Smoother.State_uncertainty;
    yU_std = sqrt(squeeze(su(yU_idx, yU_idx, :)));
    tr_std = sqrt(squeeze(su(tr_idx, tr_idx, :)));
    output_gap_lower = yU_smoothed - BAND_WIDTH_SD * yU_std;
    output_gap_upper = yU_smoothed + BAND_WIDTH_SD * yU_std;
    rstar_lower = rstar_2side - BAND_WIDTH_SD * tr_std;
    rstar_upper = rstar_2side + BAND_WIDTH_SD * tr_std;
else
    warning('export_results: oo_.Smoother.State_uncertainty not found -- was smoothed_state_uncertainty set in the estimation command? Writing NaN uncertainty columns.');
    output_gap_lower = nan(n_out, 1); output_gap_upper = nan(n_out, 1);
    rstar_lower = nan(n_out, 1); rstar_upper = nan(n_out, 1);
end

fid = fopen(fullfile(output_dir, output_csv), 'w');
fprintf(fid, ['date,rstar_2side,rstar_2side_lower,rstar_2side_upper,rstar_1side,', ...
    'output_gap_2side,output_gap_2side_lower,output_gap_2side_upper,output_gap_1side,', ...
    'unemployment_gap_2side,unemployment_gap_1side,', ...
    'trend_growth_2side,trend_growth_1side\n']);
for i = 1:n_out
    fprintf(fid, '%s,%.6f,%.6f,%.6f,%.6f,%.6f,%.6f,%.6f,%.6f,%.6f,%.6f,%.6f,%.6f\n', dates{i}, ...
        rstar_2side(i), rstar_lower(i), rstar_upper(i), rstar_1side(i), ...
        yU_smoothed(i), output_gap_lower(i), output_gap_upper(i), yU_filtered(i), ...
        uU_smoothed(i), uU_filtered(i), tg_smoothed(i), tg_filtered(i));
end
fclose(fid);

fid = fopen(fullfile(output_dir, manifest_json), 'w');
fprintf(fid, ['{\n  "last_run": "%s",\n  "model": "%s",\n', ...
    '  "data_file": "%s",\n', ...
    '  "rff_mean": %.6f,\n  "dp_mean": %.6f,\n', ...
    '  "rstar_constant": %.6f,\n', ...
    '  "rstar_constant_sample_start": "%s",\n  "rstar_constant_sample_end": "%s",\n', ...
    '  "sample_start": "%s",\n  "sample_end": "%s",\n', ...
    '  "series": ["rstar_2side", "rstar_2side_lower", "rstar_2side_upper", "rstar_1side", "output_gap_2side", "output_gap_2side_lower", "output_gap_2side_upper", "output_gap_1side", "unemployment_gap_2side", "unemployment_gap_1side", "trend_growth_2side", "trend_growth_1side"],\n', ...
    '  "files": ["%s"]\n}\n'], ...
    datestr(now, 'yyyy-mm-ddTHH:MM:SSZ'), M_.fname, data_file, rff_mean, dp_mean, ...
    rff_mean - dp_mean, RSTAR_CONST_SAMPLE_START, RSTAR_CONST_SAMPLE_END, ...
    dates{1}, dates{end}, output_csv);
fclose(fid);

% Persist this run's posterior mode as the NEXT run's warm-start point.
% Both rg_base_final.mod and rg_base_final_replication.mod specify
% mode_file=rg_base_final_mode, which Dynare reads from
% rg_base_final_mode.mat in the current directory (models/) -- but Dynare
% only ever *writes* the mode to <fname>/Output/<fname>_mode.mat, so
% without this copy step every run keeps warm-starting from whatever mode
% happened to exist the first time, not the most recent one.
% NOTE: despite this file's header comment ("Run AFTER ... from within
% models/"), Octave's run() actually cd's into THIS script's own folder
% (scripts/) before executing it -- confirmed directly (a bare
% models/-relative path silently missed here on the first attempt at
% this warm-start feature). Use '../models/'-relative paths, matching
% output_dir/data_file's existing convention just above, which happens
% to resolve identically from either scripts/ or models/ since both are
% siblings under the same parent -- unlike a bare relative path.
mode_src = fullfile('..', 'models', M_.fname, 'Output', [M_.fname '_mode.mat']);
mode_dst = fullfile('..', 'models', 'rg_base_final_mode.mat');
if exist(mode_src, 'file')
    copyfile(mode_src, mode_dst);
    disp(['Updated warm-start mode file from ' mode_src]);
else
    warning('export_results: expected mode file %s not found -- warm-start not updated for next run.', mode_src);
end

disp('Export complete.');
