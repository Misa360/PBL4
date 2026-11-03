/** Shared network-reset contract for the workbench and Earth view. */
export function buildNetworkConfig(state, values={}) {
  const size=values.size||state?.size||'full';
  const constellation=values.constellation||state?.constellation||'balanced';
  const forecast=values.forecast_load??state?.forecast_load??true;
  const config={size,constellation,deployment:'distributed',
    battery_j:Number(values.battery_j??state?.nodes?.find(n=>n.kind==='UAV')?.battery_capacity_j??1000),
    reserve_fraction:values.reserve_percent!=null?Number(values.reserve_percent)/100:Number(values.reserve_fraction??state?.reserve_fraction??.2),
    battery_profile:values.battery_profile||state?.battery_profile||'mixed',
    load_profile:values.load_profile||state?.load_profile||'mixed',
    traffic_pattern:values.traffic_pattern||state?.traffic_pattern||'bursty',
    state_seed:Number(values.state_seed??state?.state_seed??42),
    forecast_load:typeof forecast==='boolean'?forecast:forecast==='on',
    forecast_horizon:Number(values.forecast_horizon??state?.forecast_horizon??6)};
  if(Object.hasOwn(values,'uav_count')){
    if(values.uav_count!=='')config.uav_count=Number(values.uav_count);
  }else if(size===state?.size&&constellation===state?.constellation&&state?.uav_count!=null){
    config.uav_count=state.uav_count;
  }
  return config;
}
