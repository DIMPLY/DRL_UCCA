import os, sys, json, gzip
from glob import glob
from itertools import combinations
from collections import OrderedDict

from ucca import ioutil

from tupa.action import Actions
from tupa.oracle import Oracle
from tupa.states.state import State
from tupa.config import Config
from tupa.features.dense_features import DenseFeatureExtractor



def basename(filename):
    return os.path.basename(os.path.splitext(filename)[0])

def passage_files():
    return [[f for f in glob("data/raw/{}/*".format(dir))] for dir in ['dev-xml','train-xml']]

def load_passage(filename):
    passages = ioutil.read_files_and_dirs(filename, attempts=1, delay=0)
    try:
        return next(iter(passages))
    except StopIteration:
        return passages

class Settings:
    SETTINGS = ("implicit", "linkage", "unlabeled")
    VALUES = {"unlabeled": (None, [])}
    INCOMPATIBLE = (("linkage", "unlabeled"),)

    def __init__(self, *args):
        for attr in self.SETTINGS:
            setattr(self, attr, attr in args)

    @classmethod
    def all(cls):
        return [Settings(*c) for n in range(len(cls.SETTINGS) + 1) for c in combinations(cls.SETTINGS, n)
                if not any(all(s in c for s in i) for i in cls.INCOMPATIBLE)]

    def dict(self):
        return {attr: self.VALUES.get(attr, (False, True))[getattr(self, attr)] for attr in self.SETTINGS}

    def list(self):
        return [attr for attr in self.SETTINGS if getattr(self, attr)]

    def suffix(self):
        return "_".join([""] + self.list())

    def __str__(self):
        return "-".join(self.list()) or "default"

envTrainingData = []
allLabels = ['H', 'A', 'C', 'L', 'D', 'E', 'G', 'S', 'N', 'P', 'R', 'F', 'Terminal', 'U']
allTypes = ['SWAP', 'IMPLICIT', 'NODE', 'RIGHT-EDGE', 'LEFT-EDGE', 'RIGHT-REMOTE', 'LEFT-REMOTE', 'SHIFT', 'FINISH', 'REDUCE']
allActions = [{'type':t, 'hasLabel': False, 'label':None} for t in ['SHIFT', 'REDUCE', 'SWAP', 'FINISH']]
allActions.extend([{'type':t, 'hasLabel':True, 'label':l} for l in allLabels for t in ['IMPLICIT', 'NODE', 'RIGHT-EDGE', 'LEFT-EDGE', 'RIGHT-REMOTE', 'LEFT-REMOTE']])

def gen_actions(passage, feature_extractor):
    global envTrainingData, allLabels, allTypes, allActions
    oracle = Oracle(passage)
    state = State(passage)
    actions = Actions()
    while True:
        acts = oracle.get_actions(state, actions).values()
        type_label_maps = {a.type:a.tag for a in acts} # There should be no duplicate types with different tags since there is only one golden tree
        obs = feature_extractor.extract_features(state)['numeric']
        for act in allActions:
            cur_type = act['type']
            cur_has_label = act['hasLabel']
            cur_label = act['label']
            r = 0.0
            if cur_type in list(type_label_maps.keys()): # If action type matches
                r += 0.5
                if cur_has_label and cur_label == type_label_maps[cur_type] or not cur_has_label: # If action has no label or label matches
                    r += 0.5
            tNum = allTypes.index(cur_type)
            hasNum = int(cur_has_label)
            lNum = allLabels.index(cur_label)+1 if cur_has_label else 0
            actVec = {'type10':tNum, 'hasLabel':hasNum, 'label14':lNum}
            trainingData = {'obs':obs, 'act':actVec, 'r':r}
            envTrainingData.append(trainingData)
        action = min(acts, key=str)
        state.transition(action)
        s = str(action)
        if state.need_label:
            label, _ = oracle.get_label(state, action)
            state.label_node(label)
            s += " " + str(label)
        yield s
        if state.finished:
            break

def produce_oracle(cat, filename, feature_extractor):
    passage = load_passage(filename)
    sys.stdout.write('.')
    sys.stdout.flush()
    store_sequence_to = "data/oracles/%s/%s.txt" % (cat, basename(filename))#, setting.suffix())
    #with open(store_sequence_to, "w", encoding="utf-8") as f:
    #    for i, action in enumerate(gen_actions(passage, feature_extractor)):
    #        pass#print(action, file=f)
    for _ in gen_actions(passage, feature_extractor):
        pass



if __name__=="__main__":
    config = Config()
    setting = Settings(*('implicit'))
    config.update(setting.dict())
    config.set_format("ucca")
    feature_extractor = DenseFeatureExtractor(OrderedDict(),
                                              indexed = config.args.classifier!='mlp',
                                              hierarchical=False,
                                              node_dropout=config.args.node_dropout,
                                              omit_features=config.args.omit_features)

    filenames = passage_files()
    c = 'dev'
    for cat in filenames:
        for filename in cat:
            produce_oracle(c, filename, feature_extractor)
        c = 'train'

    # dump envTrainingData to a file for further learning in rewardNN.py
    json_str = json.dumps(envTrainingData) + "\n"
    json_bytes = json_str.encode('utf-8')
    with gzip.GzipFile('env-train.json', 'w') as fout:
        fout.write(json_bytes)
    with gzip.GzipFile('env-train-copy.json', 'w') as fout:
        fout.write(json_bytes)