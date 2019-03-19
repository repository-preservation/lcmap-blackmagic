from blackmagic import cfg
from blackmagic import db
from blackmagic import skip_on_exception
from blackmagic import workers
from cytoolz import assoc
from cytoolz import do
from cytoolz import drop
from cytoolz import first
from cytoolz import get
from cytoolz import get_in
from cytoolz import merge
from cytoolz import partial
from cytoolz import reduce
from cytoolz import second
from cytoolz import thread_first
from flask import Blueprint
from flask import jsonify
from flask import request
from merlin.functions import flatten
from sklearn.model_selection import train_test_split

import arrow
import logging
import io
import merlin
import numpy
import xgboost as xgb

logger = logging.getLogger('blackmagic.tile')
tile = Blueprint('tile', __name__)


def aux(cx, cy, cfg):
    '''Retrieve aux data'''
    
    data = merlin.create(x=cx,
                         y=cy,
                         acquired='1982/2018',
                         cfg=merlin.cfg.get(profile='chipmunk-aux',
                                            env={'CHIPMUNK_URL': cfg['aux_url']}))
    
    return {first(d): second(d) for d in merlin.functions.denumpify(data)}

    
def segments(cx, cy, cfg):
    '''Return segments stored in Cassandra'''
    
    return [r for r in db.execute_statement(cfg, db.select_segment(cfg, cx, cy))]


def datefilter(date, segments):
    '''Yield segments that span the supplied date'''

    d = arrow.get(date).datetime
    
    for s in segments:
        if (d >= arrow.get(s.sday).datetime and
            d <= arrow.get(s.eday).datetime):
            yield s

             
def combine(segments, aux):
    '''Combine segments with matching aux entry'''

    for s in segments:
        key = (s.cx, s.cy, s.px, s.py)
        yield merge(aux[key], s._asdict())


def format(entries):
    '''Properly format training entries'''

    '''
    {'nlcdtrn': [2], 'aspect': [0], 'posidex': [25.0], 'nlcd': [82], 'slope': [6.3103461265563965], 'mpw': [0], 'dem': [276.5125427246094], 'dates': ['2000-07-31T00:00:00Z/2001-01-01T00:00:00Z'], 'cx': 1646415, 'cy': 2237805, 'px': 1649385, 'py': 2235045, 'sday': '1984-03-24', 'eday': '2016-10-06', 'bday': '2016-10-06', 'blcoef': [-0.010404632426798344, 54.50187301635742, 101.96070861816406, -38.63310623168945, -3.4969518184661865, 0.0, -38.35179138183594], 'blint': 8016.1611328125, 'blmag': 93.25048828125, 'blrmse': 140.84637451171875, 'chprob': 0.0, 'curqa': 8, 'grcoef': [-0.014921323396265507, -13.973718643188477, 126.78702545166016, -62.550445556640625, -22.54693603515625, 4.363803386688232, -13.57226276397705], 'grint': 11458.1923828125, 'grmag': 85.9715805053711, 'grrmse': 140.90208435058594, 'nicoef': [0.001133676152676344, -1567.1834716796875, -167.4553680419922, 355.0714416503906, 191.9523468017578, -142.80911254882812, 342.6976013183594], 'niint': 1595.630126953125, 'nimag': 212.36441040039062, 'nirmse': 421.1643371582031, 'recoef': [-0.016207082197070122, 104.48441314697266, 211.29937744140625, -158.95477294921875, -42.79849624633789, -19.37449836730957, -89.44105529785156], 'reint': 12387.9248046875, 'remag': 69.07315826416016, 'rermse': 137.7318878173828, 's1coef': [-0.02014756016433239, -300.4599609375, 386.727294921875, -299.61871337890625, -55.58943557739258, -62.033470153808594, -161.67315673828125], 's1int': 16410.873046875, 's1mag': 89.79656219482422, 's1rmse': 272.87200927734375, 's2coef': [-0.01282140240073204, 29.842893600463867, 383.56500244140625, -260.76898193359375, -67.41301727294922, -13.364554405212402, -178.7677459716797], 's2int': 10256.634765625, 's2mag': 119.9651870727539, 's2rmse': 196.84481811523438, 'thcoef': [0.0017974661896005273, -1176.3935546875, -116.62395477294922, -229.40621948242188, -38.72520065307617, 11.268446922302246, -49.42088317871094], 'thint': -226.81626892089844, 'thmag': 251.63075256347656, 'thrmse': 417.1956481933594}

    '''

    training = [[get('nlcdtrn', e),
                 get('aspect' , e),
                 get('posidex', e),
                 get('slope'  , e),
                 get('mpw'    , e),
                 get('dem'    , e),
                 get('blcoef' , e),
                 [get('blint'  , e)],
                 [get('blmag'  , e)],
                 [get('blrmse' , e)],
                 get('grcoef' , e),
                 [get('grint'  , e)],
                 [get('grmag'  , e)],
                 [get('grrmse' , e)],
                 get('nicoef' , e),
                 [get('niint'  , e)],
                 [get('nimag'  , e)],
                 [get('nirmse' , e)],
                 get('recoef' , e),
                 [get('reint'  , e)], 
                 [get('remag'  , e)],
                 [get('rermse' , e)],
                 get('s1coef' , e),
                 [get('s1int'  , e)],
                 [get('s1mag'  , e)],
                 [get('s1rmse' , e)],
                 get('s2coef' , e),
                 [get('s2int'  , e)],
                 [get('s2mag'  , e)],
                 [get('s2rmse' , e)],
                 get('thcoef' , e),
                 [get('thint'  , e)],
                 [get('thmag'  , e)],
                 [get('thrmse' , e)]] for e in entries]

    return [numpy.array(list(flatten(t)), dtype=numpy.float64) for t in training]


def dmatrix(data, labels):
    '''Transforms independent and dependent variables into an xgboost dmatrix'''

    return xgb.DMatrix(data, labels)


def independent(data):
    '''Independent variable is (are) all the values except the labels
        data: 2d numpy array
        return: 2d numpy array minus the labels (first element of every row)
    '''
    
    return numpy.delete(data, 0, 1)


def dependent(data):
    '''Dependent variable is (are) the labels
       data: 2d numpy array
       return: 1d numpy array of labels
    '''
    
    return numpy.delete(data, numpy.s_[1:], 1).flatten()


#def parameters():
#    '''Parameters for xgboost training'''
#    return {'objective': 'multi:softprob',
#            'num_class': 9,
#            'max_depth': 8,
#            'tree_method': 'hist',
#            'eval_metric': 'mlogloss',
#            'silent': 1,
#            'nthread': -1}


def watchlist(training_data, eval_data):
    return [(training_data, 'train'), (eval_data, 'eval')]


def pipeline(chip, date, cfg):
    '''Retrieve segment and label data for one chip'''
    cx=first(chip)
    cy=second(chip)
    
    return format(combine(segments=datefilter(date=date, segments=segments(cx=cx, cy=cy, cfg=cfg)),
                          aux=aux(cx=cx, cy=cy, cfg=cfg)))


#@tile.route('/tile', methods=['POST'])
#def tile_fn():
#    r = request.json
#    x = get('tx', r, None)
#    y = get('ty', r, None)
#    c = get('chips', r, None)
#    d = get('date', r, None)
#
#    if (x is None or y is None or c is None or d is None):
#        response = jsonify({'tx': tx, 'ty': ty, 'chips': chips, 'date': date,
#                            'msg': 'tx, ty, chips and date are required parameters'})
#        response.status_code = 400
#        return response
#
#    logger.info('POST /tile {x},{y},{d},{c}'.format(x=x, y=y, d=d, c=c))
#    
#    try:
#        __queue   = parallel.queue()
#        __workers = parallel.workers(cfg)
#
#        # data is going to be about 20GB
#        f = partial(pipeline, date=d)
#        data = __workers.map(f, c)
#        
#        _ = save(tx=x,
#                 ty=y,
#                 model=train(sample(numpy.array(list(flatten(data)), parameters()))))
#
#        return jsonify({'tx': x, 'ty': y, 'date': d, 'chips': c})
#    
#    except Exception as e:
#        logger.exception(e)
#        raise e
#    finally:
#
#        logger.debug('stopping workers')
#        __workers.terminate()
#        __workers.join()


@skip_on_exception
def parameters(r):
    '''Check HTTP request parameters'''
    
    tx       = get('tx', r, None)
    ty       = get('ty', r, None)
    chips    = get('chips', r, None)
    date     = get('date', r, None)
    
    test_pixel_count         = int(get('test_pixel_count', r, 10000))
    test_detection_exception = get('test_detection_exception', r, None)
    test_cassandra_exception = get('test_cassandra_exception', r, None)
    
    if (tx is None or ty is None or chips is None or date is None):
        raise Exception('tx, ty, chips and date are required parameters')
    else:
        return {'tx': int(tx),
                'ty': int(ty),
                'date': date,
                'chips': chips}


def log_request(ctx):
    '''Create log message for HTTP request'''

    tx = get('tx', ctx, None)
    ty = get('ty', ctx, None)
    d  = get('date', ctx, None)
    c  = get('chips', ctx, None)
    
    logger.info('POST /tile {x},{y},{d},{c}'.format(x=tx, y=ty, d=d, c=c))
        
    return ctx


def exception_handler(ctx, http_status, name, fn):
    try:
        return fn(ctx)
    except Exception as e:        
        return do(logger.exception, {'tx': get('tx', ctx, None),
                                 'ty': get('ty', ctx, None),
                                 'date': get('date', ctx, None),
                                 'chips': get('chips', ctx, None),
                                 'exception': '{name} exception: {ex}'.format(name=name, ex=e),
                                 'http_status': http_status})
    

@skip_on_exception
def data(ctx, cfg):
    '''Retrieve training data for all chips in parallel'''
    
    p = partial(pipeline, date=ctx['date'], cfg=cfg)
    
    with workers(cfg) as w:
        return assoc(ctx, 'data', numpy.array(list(flatten(w.map(p, ctx['chips'])))))


def counts(data):
    '''Count the occurance of each label in data'''
    
    c = Counter()
    
    for d in data:
        c[first(d)] += 1
        
    return c

    
@skip_on_exception
def statistics(ctx, cfg):
    '''Count label occurences'''

    # 1.
    # generate class statistics... how many labels of each type exist in the dataset, and what
    # % are they of the whole
    #
    #     with workers(cfg) as w:
    #         counters = w.map(counts, ctx['data'])
    #         c = Counter()
    #         map(c.update, counters)
    #         return assoc(ctx, 'statistics', c)
    #
    #
    # see collections.Counter

    return ctx


@skip_on_exception
def randomize(ctx, cfg):
    '''Randomize the order of training data'''

    # return assoc(ctx, 'data', np.random.RandomState().permutation(ctx['data']))

    return ctx

    
@skip_on_exception
def sample(ctx, cfg):
    '''Return leveled data sample based on label values'''

    # See xg-train-annualized.py in lcmap-science/classification as reference.
    
    # 1.
    # generate class statistics... how many labels of each type exist in the dataset, and what
    # % are they of the whole

    # 2.
    # parameterize the number of desired total samples (as a request parameter, it depends on the area being sampled).
    # multiply the desired sample size by each percentage to determine how many samples
    # to take from each label.

    # 3.
    # Randomize ctx['data'] and select up to the proper count for each label

    # 4.
    # Reassigned ctx['data'] to the sampled data.

    #     ctx['statistics']
    
    #return assoc(ctx, 'data', 'sampled data')

    return ctx


@skip_on_exception
def train(ctx, cfg):
    '''Train an xgboost model'''
    
    itrain, itest, dtrain, dtest = train_test_split(independent(ctx['data']),
                                                    dependent(ctx['data']),
                                                    test_size=get_in(['xgboost', 'test_size'], cfg))
    
    train_matrix = xgb.DMatrix(data=itrain, label=dtrain)
    test_matrix  = xgb.DMatrix(data=itest, label=dtest)
    
    return assoc(ctx, 'model', xgb.train(params=get_in(['xgboost', 'parameters'], cfg),
                                         dtrain=train_matrix,
                                         num_boost_round=get_in(['xgboost', 'num_round'], cfg),
                                         evals=watchlist(train_matrix, test_matrix),
                                         early_stopping_rounds=get_in(['xgboost', 'early_stopping_rounds'], cfg),
                                         verbose_eval=get_in(['xgboost', 'verbose_eval'], cfg)))


@skip_on_exception
def save(ctx, cfg):                                                
    '''Saves an xgboost model to Cassandra for this tx & ty'''
   
    db.execute2(cfg, **db.insert_tile(cfg,
                                      ctx['tx'],
                                      ctx['ty'],
                                      ctx['model'].save_raw()))
    
    return ctx


def respond(ctx):
    '''Send the HTTP response'''

    body = {'tx': get('tx', ctx, None),
            'ty': get('ty', ctx, None),
            'date': get('date', ctx, None),
            'chips': get('chips', ctx, None)}

    e = get('exception', ctx, None)
    
    if e:
        response = jsonify(assoc(body, 'exception', e))
    else:
        response = jsonify(body)

    response.status_code = get('http_status', ctx, 200)

    return response


@tile.route('/train', methods=['POST'])        
def tiles():
    return thread_first(request.json,
                        partial(exception_handler, http_status=500, name='log_request', fn=log_request),
                        partial(exception_handler, http_status=400, name='parameters', fn=parameters),
                        partial(exception_handler, http_status=500, name='data', fn=partial(data, cfg=cfg)),
                        partial(exception_handler, http_status=500, name='statistics', fn=partial(statistics, cfg=cfg)),
                        partial(exception_handler, http_status=500, name='randomize', fn=partial(randomize, cfg=cfg)),
                        partial(exception_handler, http_status=500, name='sample', fn=partial(sample, cfg=cfg)),
                        partial(exception_handler, http_status=500, name='train', fn=partial(train, cfg=cfg)),
                        partial(exception_handler, http_status=500, name='save', fn=partial(save, cfg=cfg)),
                        respond)
