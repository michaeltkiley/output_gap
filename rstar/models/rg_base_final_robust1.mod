// Michael Kiley, Federal Reserve Board
// 

// Simple trend/cycle decomp with credit...


var yU, t1, leady, yobs, dyobs, lur, uU, t3, dp, dlur, ptr,rff,tr,tg,dp4;
varexo e_rff, e_ptr, e_dp, e_t2, e_t4, e_yu, e_tr, eg,e_yobs;

parameters  rhoy1, rhoy2, ry, uy, dp1, dp2, dpu;

rhoy1 = 1.5;
rhoy2 = 0.6; 
uy = -.4;
dpu=-.1;
dp1=.3;
dp2=.3;
ry = 0.1;

model;
dp4 = (dp+dp(-1)+dp(-2)+dp(-3))/4;
dp = dp1*dp(-1) + dp2*(dp(-2)+dp(-3)+dp(-4))/3 + (1-dp1-dp2)*ptr(-1) + dpu*uU + e_dp;
uU = uy*(.4*yU+.3*yU(-1)+.2*yU(-2)+.1*yU(-3)) ;
yU = rhoy1*yU(-1) - rhoy2*yU(-2) - ry*(rff(-1)-dp4(-1)-tr(-1)+rff(-2)-dp4(-2)-tr(-2))/2 + e_yu ;
tg = tg(-1) + eg;
tr = tr(-1) + e_tr;
t3 = t3(-1) + e_t4;
t1 = t1(-1) + tg + e_t2;
leady = yU(+1);
// measurement equations
yobs=t1+yU + e_yobs;
dyobs = 4*(yobs-yobs(-1));
lur = uU + t3 ;
dlur = lur-lur(-1);
ptr = ptr(-1) + e_ptr;
rff = rff(-1) + e_rff;
end;


shocks;
var e_yobs; stderr 0;
end;


estimated_params;
// PARAM NAME, INITVAL, LB, UB, PRIOR_SHAPE, PRIOR_P1, PRIOR_P2, PRIOR_P3, PRIOR_P4, JSCALE
// PRIOR_SHAPE: BETA_PDF, GAMMA_PDF, NORMAL_PDF, INV_GAMMA_PDF
stderr e_rff, 1, 0.0001, 1000,UNIFORM_PDF,.0001,100; 
stderr e_ptr, .25, 0.0001, 1000,UNIFORM_PDF,.0001,100; 
stderr e_dp, 1, 0.0001, 1000,INV_GAMMA_PDF,2,2; 
stderr e_t2, .5, 0.0001, 1000,INV_GAMMA_PDF,.25,.25;
stderr e_t4, .05, 0.0001, 1000,INV_GAMMA_PDF,.25,5;
stderr e_yu, .5, 0.0001, 1000,INV_GAMMA_PDF,2,2;
stderr e_tr, .05, 0.0001, 1000,INV_GAMMA_PDF,.25,5;
stderr eg, .05, 0.0001, 1000,INV_GAMMA_PDF,.25,5;
rhoy1, 1.2, -10, 10, NORMAL_PDF, 0,2;
rhoy2, 0.25, -10, 10, NORMAL_PDF, 0,2;
ry,.1, -10, 10, NORMAL_PDF, 0,2;
uy,-.5, -10, 10, NORMAL_PDF, 0,2;
dp1, .33, -10, 10, NORMAL_PDF, 0,2;
dp2, .33, -10,10, NORMAL_PDF, 0,2;
dpu, -.2, -10, 10, NORMAL_PDF, 0,2;
end;

varobs dyobs lur dp ptr rff tr;

estimation(tex,order=1,optim=('MaxIter',1000,'Tolfun',1.0e-06),datafile='rstardata',mode_compute=5,mode_file=rg_base_final_mode,first_obs=5,presample=4,lik_init=2,prefilter=1,mh_replic=500000,mh_nblocks=2,mh_jscale=0.5,mh_drop=0.2,filtered_vars,smoothed_state_uncertainty) uU tr tg;


// smoothed and filtered estimates of real GDP
stoch_simul(order=1,nograph);
