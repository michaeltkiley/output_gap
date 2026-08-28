% export_results.m
% Run AFTER `dynare linearized.mod noclearall` (from within models/) --
% pulls the calib_smoother's GAP/PFGAP estimates out of oo_ and writes
% plain CSV/JSON for the website.
%
% Optionally set `data_file` and `output_csv` in the workspace before
% calling this (e.g. for the --detrend-all robustness variant); otherwise
% defaults to the standard pipeline paths.

if ~exist('data_file', 'var')
    data_file = '../data/observables.csv';
end
if ~exist('output_csv', 'var')
    output_csv = 'output_gap.csv';
end
if ~exist('manifest_json', 'var')
    manifest_json = 'manifest.json';
end

output_dir = '../outputs';
if ~exist(output_dir, 'dir')
    mkdir(output_dir);
end

% Re-read the observation dates from the same file fed to calib_smoother,
% since oo_.SmoothedVariables carries values but not dates.
fid = fopen(data_file);
header = fgetl(fid); %#ok<NASGU> -- "Variables ->,..."
dates = {};
line = fgetl(fid);
while ischar(line)
    parts = strsplit(line, ',');
    dates{end+1} = parts{1}; %#ok<AGROW>
    line = fgetl(fid);
end
fclose(fid);

gap = oo_.SmoothedVariables.GAP(:);
pfgap = oo_.SmoothedVariables.PFGAP(:);

if numel(dates) ~= numel(gap)
    error('export_results: %d dates but %d smoothed GAP observations -- sample mismatch', ...
        numel(dates), numel(gap));
end

fid = fopen(fullfile(output_dir, output_csv), 'w');
fprintf(fid, 'date,GAP,PFGAP\n');
for i = 1:numel(gap)
    fprintf(fid, '%s,%.6f,%.6f\n', dates{i}, gap(i), pfgap(i));
end
fclose(fid);

fid = fopen(fullfile(output_dir, manifest_json), 'w');
fprintf(fid, ['{\n  "last_run": "%s",\n  "model": "%s",\n', ...
    '  "data_file": "%s",\n', ...
    '  "sample_start": "%s",\n  "sample_end": "%s",\n', ...
    '  "series": ["GAP", "PFGAP"],\n  "files": ["%s"]\n}\n'], ...
    datestr(now, 'yyyy-mm-ddTHH:MM:SSZ'), M_.fname, data_file, dates{1}, dates{end}, output_csv);
fclose(fid);

disp('Export complete.');
