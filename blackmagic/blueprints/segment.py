from blackmagic import cfg
from blackmagic import db
from blackmagic import parallel
from cytoolz import assoc
from cytoolz import count
from cytoolz import excepts
from cytoolz import first
from cytoolz import get
from cytoolz import get_in
from cytoolz import partial
from cytoolz import second
from cytoolz import take
from datetime import date
from datetime import datetime
from flask import Blueprint
from flask import jsonify
from flask import request
from merlin.functions import flatten
from multiprocessing import Pool
from multiprocessing import Process
from multiprocessing import Manager

import ccd
import logging
import merlin
import os
import sys

logger  = logging.getLogger('blackmagic.segment')
segment = Blueprint('segment', __name__)


def save_chip(detections):
    db.insert_chips(cfg, detections)
    return detections
    

def save_pixels(detections):
    db.insert_pixels(cfg, detections)
    return detections


def save_segments(detections):
    db.insert_segments(cfg, detections)
    return detections


def defaults(cms):
    return [{}] if (not cms or len(cms) == 0) else cms

    
def coefficients(change_model, spectra):
    coefs = get_in([spectra, 'coefficients'], change_model)
    return list(coefs) if coefs else []


def format(cx, cy, px, py, dates, ccdresult):
    
    return [
             {'cx'     : int(cx),
              'cy'     : int(cy),
              'px'     : int(px),
              'py'     : int(py),
              'sday'   : date.fromordinal(get('start_day', cm, 1)).isoformat(),
              'eday'   : date.fromordinal(get('end_day', cm, 1)).isoformat(),
              'bday'   : date.fromordinal(get('break_day', cm, 1)).isoformat(),
              'chprob' : get('change_probability', cm, 0.0),
              'curqa'  : get('curve_qa', cm, 0),
              'blmag'  : get_in(['blue', 'magnitude'], cm, 0.0),
              'grmag'  : get_in(['green', 'magnitude'], cm, 0.0),
              'remag'  : get_in(['red', 'magnitude'], cm, 0.0),
              'nimag'  : get_in(['nir', 'magnitude'], cm, 0.0),
              's1mag'  : get_in(['swir1', 'magnitude'], cm, 0.0),
              's2mag'  : get_in(['swir2', 'magnitude'], cm, 0.0),
              'thmag'  : get_in(['thermal', 'magnitude'], cm, 0.0),
              'blrmse' : get_in(['blue', 'rmse'], cm, 0.0),
              'grrmse' : get_in(['green', 'rmse'], cm, 0.0),
              'rermse' : get_in(['red', 'rmse'], cm, 0.0),
              'nirmse' : get_in(['nir', 'rmse'], cm, 0.0),
              's1rmse' : get_in(['swir1', 'rmse'], cm, 0.0),
              's2rmse' : get_in(['swir2', 'rmse'], cm, 0.0),
              'thrmse' : get_in(['thermal', 'rmse'], cm, 0.0),
              'blcoef' : coefficients(cm, 'blue'),
              'grcoef' : coefficients(cm, 'green'),
              'recoef' : coefficients(cm, 'red'),
              'nicoef' : coefficients(cm, 'nir'),
              's1coef' : coefficients(cm, 'swir1'),
              's2coef' : coefficients(cm, 'swir2'),
              'thcoef' : coefficients(cm, 'thermal'),
              'blint'  : get_in(['blue', 'intercept'], cm, 0.0),
              'grint'  : get_in(['green', 'intercept'], cm, 0.0),
              'reint'  : get_in(['red', 'intercept'], cm, 0.0),
              'niint'  : get_in(['nir', 'intercept'], cm, 0.0),
              's1int'  : get_in(['swir1', 'intercept'], cm, 0.0),
              's2int'  : get_in(['swir2', 'intercept'], cm, 0.0),
              'thint'  : get_in(['thermal', 'intercept'], cm, 0.0),
              'dates'  : [date.fromordinal(o).isoformat() for o in dates],
              'mask'   : get('processing_mask', ccdresult)}
        
             for cm in defaults(get('change_models', ccdresult, None))]


def detect(timeseries):
   
    cx, cy, px, py = first(timeseries)

    return format(cx=cx,
                  cy=cy,
                  px=px,
                  py=py,
                  dates=get('dates', second(timeseries)),
                  ccdresult=ccd.detect(**second(timeseries)))


def delete_detections(timeseries):
    cx, cy, _, _ = first(first(timeseries))
    try:
        x = int(cx)
        y = int(cy)
        db.execute_statements(cfg, [db.delete_chip(cfg, x, y),
                                    db.delete_pixel(cfg, x, y),
                                    db.delete_segment(cfg, x, y)])
    except Exception as e:
        logger.exception('Exception deleting partition for cx:{cx} cy:{cy}'.format(cx=x, cy=y))
        raise e
    return timeseries


def workers(cfg):
    return Pool(cfg['cpus_per_worker'])


def measure(name, start_time, cx, cy, acquired):
    e = datetime.now()
    d = {'cx': cx, 'cy': cy, 'acquired': acquired}
    d = assoc(d, '{name}_elapsed_seconds'.format(name=name), (e - start_time).total_seconds())
    logger.info(d)
    return d


@segment.route('/oldsegment', methods=['POST'])
def segment():
    r = request.json
    x = get('cx', r, None)
    y = get('cy', r, None)
    a = get('acquired', r, None)
    n = int(get('n', r, 10000))

    test_detection_exception = get('test_detection_exception', r, None)
    test_cassandra_exception = get('test_cassandra_exception', r, None)
    
    if (x is None or y is None or a is None):
        response = jsonify({'cx': x, 'cy': y, 'acquired': a, 'msg': 'cx, cy, and acquired are required parameters'})
        response.status_code = 400
        return response

    logger.info('POST /segment {x},{y},{a}'.format(x=x, y=y, a=a))

    merlin_start = datetime.now()
    try:
        timeseries = merlin.create(x=x,
                                   y=y,
                                   acquired=a,
                                   cfg=merlin.cfg.get(profile='chipmunk-ard',
                                                      env={'CHIPMUNK_URL': cfg['chipmunk_url']}))
    except Exception as ex:
        measure('merlin_exception', merlin_start, x, y, a)
        logger.exception('Merlin exception in /segment:{}'.format(ex))
        response = jsonify({'cx': x, 'cy': y, 'acquired': a, 'msg': str(ex)})
        response.status_code = 500
        return response
    
    if count(timeseries) == 0:
        measure('merlin_no_input_data_exception', merlin_start, x, y, a)
        logger.warning('No input data for {cx},{cy},{a}'.format(cx=x, cy=y, a=a))
        response = jsonify({'cx': x, 'cy': y, 'acquired': a, 'msg': 'no input data'})
        response.status_code = 500
        return response
    
    measure('merlin', merlin_start, x, y, a)

    detection_start = None
    cassandra_start = None
    detections = None

    try:        
        with workers(cfg) as __workers:
            detection_start = datetime.now()

            if test_detection_exception:
                raise Exception('test_detection_exception')
        
            detections = list(flatten(__workers.map(detect, take(n, delete_detections(timeseries)))))
            measure('detection', detection_start, x, y, a)
    except Exception as ex:
        measure('detection_exception', detection_start, x, y, a)
        logger.exception("Detection exception in /segment:{}".format(ex))
        response = jsonify({'cx': x, 'cy': y, 'acquired': a, 'msg': str(ex)})
        response.status_code = 500
        return response
    
    try:    
        cassandra_start = datetime.now()

        if test_cassandra_exception:
                raise Exception('test_detection_exception')
            
        save_segments(save_pixels(save_chip(detections)))
        measure('cassandra', cassandra_start, x, y, a)    
        return jsonify({'cx': x, 'cy': y, 'acquired': a})
    except Exception as ex:
        measure('cassandra_exception', cassandra_start, x, y, a)
        logger.exception("Cassandra exception in /segment:{}".format(ex))
        response = jsonify({'cx': x, 'cy': y, 'acquired': a, 'msg': str(ex)})
        response.status_code = 500
        return response
