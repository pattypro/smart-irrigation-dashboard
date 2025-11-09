from __future__ import annotations
from dataclasses import dataclass
from datetime import date
from typing import Optional, Tuple, Dict

@dataclass
class StageParams:
    kc_ini: float = 0.60
    kc_mid: float = 1.05
    kc_late: float = 0.95
    zr_ini_m: float = 0.20
    zr_mid_m: float = 0.30
    zr_late_m: float = 0.35
    p_ini: float = 0.50
    p_mid: float = 0.45
    p_late: float = 0.55

@dataclass
class SoilParams:
    theta_fc: float = 0.30
    theta_wp: float = 0.12
    alpha: float = 0.60

@dataclass
class NDVI2Kc:
    a: float = 1.25
    b: float = 0.20
    kc_min: float = 0.30
    kc_max: float = 1.10
    active_gate: float = 0.80

@dataclass
class Config:
    transplant_date: date
    efficiency: float = 0.85
    area_m2: float = 1.0
    rain_skip_mm: float = 2.0
    stage: StageParams = StageParams()
    soil: SoilParams = SoilParams()
    ndvi2kc: NDVI2Kc = NDVI2Kc()
    strict_t4_and: bool = True

PLOTS = ["T1","T2","T3","T4"]

def days_after_transplant(d: date, transplant: date) -> int:
    return (d - transplant).days

def stage_of_day(dat: int) -> str:
    if dat <= 20: return "ini"
    if dat <= 45: return "mid"
    return "late"

def stage_params_for(dat: int, cfg: Config) -> Tuple[float,float,float]:
    stg = stage_of_day(dat)
    if stg == "ini":
        return cfg.stage.kc_ini, cfg.stage.zr_ini_m, cfg.stage.p_ini
    elif stg == "mid":
        return cfg.stage.kc_mid, cfg.stage.zr_mid_m, cfg.stage.p_mid
    else:
        return cfg.stage.kc_late, cfg.stage.zr_late_m, cfg.stage.p_late

def kc_from_stage(dat: int, cfg: Config) -> float:
    kc,_,_ = stage_params_for(dat, cfg)
    return kc

def kc_from_ndvi(ndvi: Optional[float], cfg: Config, fallback_kc: float) -> float:
    if ndvi is None:
        return fallback_kc
    kc = cfg.ndvi2kc.a * ndvi + cfg.ndvi2kc.b
    kc = max(cfg.ndvi2kc.kc_min, min(cfg.ndvi2kc.kc_max, kc))
    return float(kc)

def taw_raw(theta_fc: float, theta_wp: float, zr_m: float, p: float) -> Tuple[float,float]:
    taw = (theta_fc - theta_wp) * zr_m * 1000.0
    raw = p * taw
    return taw, raw

def theta_trigger(theta_fc: float, theta_wp: float, alpha: float) -> float:
    return theta_wp + alpha * (theta_fc - theta_wp)

def peff(rain_obs_mm: float) -> float:
    return max(0.0, 0.8 * float(rain_obs_mm))

def decide_T2(d: date, ETo: float, rain_obs: float, rain_fcst_24h: float,
              theta_vwc: Optional[float], Dr_start: float, cfg: Config) -> Dict:
    dat = days_after_transplant(d, cfg.transplant_date)
    kc_stg, zr_m, p = stage_params_for(dat, cfg)
    ETc = ETo * kc_stg
    TAW, RAW = taw_raw(cfg.soil.theta_fc, cfg.soil.theta_wp, zr_m, p)
    RAW_stage = RAW * (0.8 if dat <= 20 else (1.2 if dat > 45 else 1.0))
    Dr_end = max(0.0, Dr_start + ETc - peff(rain_obs))

    trig_wb = Dr_start > RAW_stage
    trig_soil = (theta_vwc is not None) and (theta_vwc < theta_trigger(cfg.soil.theta_fc, cfg.soil.theta_wp, cfg.soil.alpha))
    skip_fcst = rain_fcst_24h >= cfg.rain_skip_mm

    irrigate = (trig_wb or trig_soil) and (not skip_fcst)

    irr_net = Dr_start if irrigate else 0.0
    irr_gross = irr_net / cfg.efficiency if irrigate else 0.0
    liters = irr_gross * cfg.area_m2

    return dict(plot="T2", date=d.isoformat(), decision="Irrigate" if irrigate else "Skip",
                reason=("WB" if trig_wb else "") + (" & Soil" if trig_soil and irrigate else ("")),
                dat=dat, stage=stage_of_day(dat), ETo=ETo, rain_obs=rain_obs, rain_fcst=rain_fcst_24h,
                kc=kc_stg, ETc=ETc, zr_m=zr_m, p=p, TAW=TAW, RAW=RAW_stage, Dr_start=Dr_start, Dr_end=Dr_end if not irrigate else 0.0,
                theta_vwc=theta_vwc, theta_trigger=theta_trigger(cfg.soil.theta_fc, cfg.soil.theta_wp, cfg.soil.alpha),
                irr_net_mm=irr_net, irr_gross_mm=irr_gross, irr_liters=liters)

def decide_T3(d: date, ETo: float, rain_obs: float, rain_fcst_24h: float,
              ndvi: Optional[float], Dr_start: float, cfg: Config) -> Dict:
    dat = days_after_transplant(d, cfg.transplant_date)
    kc_stg, zr_m, p = stage_params_for(dat, cfg)
    kc_ndvi = kc_from_ndvi(ndvi, cfg, kc_stg)
    ETc = ETo * kc_ndvi
    TAW, RAW = taw_raw(cfg.soil.theta_fc, cfg.soil.theta_wp, zr_m, p)
    Dr_end = max(0.0, Dr_start + ETc - peff(rain_obs))

    trig_active = kc_ndvi >= cfg.ndvi2kc.active_gate
    trig_wb = Dr_start > RAW
    skip_fcst = rain_fcst_24h >= cfg.rain_skip_mm

    irrigate = (trig_wb and trig_active) and (not skip_fcst)

    irr_net = Dr_start if irrigate else 0.0
    irr_gross = irr_net / cfg.efficiency if irrigate else 0.0
    liters = irr_gross * cfg.area_m2

    return dict(plot="T3", date=d.isoformat(), decision="Irrigate" if irrigate else "Skip",
                reason=("WB&ActiveNDVI" if irrigate else ("Forecast≥2mm" if skip_fcst else ("WB≤RAW/NDVI gate"))),
                dat=dat, stage=stage_of_day(dat), ETo=ETo, rain_obs=rain_obs, rain_fcst=rain_fcst_24h,
                ndvi=ndvi, kc=kc_ndvi, ETc=ETc, zr_m=zr_m, p=p, TAW=TAW, RAW=RAW, Dr_start=Dr_start, Dr_end=Dr_end if not irrigate else 0.0,
                irr_net_mm=irr_net, irr_gross_mm=irr_gross, irr_liters=liters)

def decide_T4_strict(d: date, ETo: float, rain_obs: float, rain_fcst_24h: float,
                     ndvi: Optional[float], theta_vwc: Optional[float], Dr_start: float, cfg: Config) -> Dict:
    dat = days_after_transplant(d, cfg.transplant_date)
    kc_stg, zr_m, p = stage_params_for(dat, cfg)
    kc_ndvi = kc_from_ndvi(ndvi, cfg, kc_stg)
    ETc = ETo * kc_ndvi
    TAW, RAW = taw_raw(cfg.soil.theta_fc, cfg.soil.theta_wp, zr_m, p)
    RAW_stage = RAW * (0.8 if dat <= 20 else (1.2 if dat > 45 else 1.0))
    Dr_end = max(0.0, Dr_start + ETc - peff(rain_obs))

    trig_wb   = Dr_start > RAW_stage
    trig_soil = (theta_vwc is not None) and (theta_vwc < theta_trigger(cfg.soil.theta_fc, cfg.soil.theta_wp, cfg.soil.alpha))
    trig_ndvi = kc_ndvi >= cfg.ndvi2kc.active_gate
    trig_fcst = rain_fcst_24h < cfg.rain_skip_mm

    irrigate = bool(trig_wb and trig_soil and trig_ndvi and trig_fcst)

    irr_net = Dr_start if irrigate else 0.0
    irr_gross = irr_net / cfg.efficiency if irrigate else 0.0
    liters = irr_gross * cfg.area_m2

    return dict(plot="T4", date=d.isoformat(), decision="Irrigate" if irrigate else "Skip",
                reason=f"AND: WB={trig_wb}, Soil={trig_soil}, NDVI={trig_ndvi}, Fcst={trig_fcst}",
                dat=dat, stage=stage_of_day(dat), ETo=ETo, rain_obs=rain_obs, rain_fcst=rain_fcst_24h,
                ndvi=ndvi, theta_vwc=theta_vwc, kc=kc_ndvi, ETc=ETc, zr_m=zr_m, p=p, TAW=TAW, RAW=RAW_stage,
                Dr_start=Dr_start, Dr_end=Dr_end if not irrigate else 0.0,
                theta_trigger=theta_trigger(cfg.soil.theta_fc, cfg.soil.theta_wp, cfg.soil.alpha),
                irr_net_mm=irr_net, irr_gross_mm=irr_gross, irr_liters=liters,
                gates=dict(WB=trig_wb, Soil=trig_soil, NDVI=trig_ndvi, Fcst=trig_fcst))
