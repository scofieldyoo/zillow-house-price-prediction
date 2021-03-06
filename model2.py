import numpy as np
import pandas as pd
import xgboost as xgb
from sklearn.preprocessing import LabelEncoder
import utils
import zipfile
from sklearn.preprocessing import StandardScaler

# res:0.064425
properties = pd.read_csv(utils.file_properties)
train = pd.read_csv(utils.file_train)

print('start to preprocess')
for c in properties.columns:
    if properties[c].dtype == np.float64:
        properties[c].fillna(properties[c].median(), inplace=True)
        properties[c] = properties[c].astype(np.float32)
    if properties[c].dtype == 'object':
        properties[c].fillna(0, inplace=True)
        lbl = LabelEncoder()
        lbl.fit(list(properties[c].values))
        properties[c] = lbl.transform(list(properties[c].values))

feat = ['propertycountylandusecode', 'fireplaceflag', 'taxdelinquencyflag']
for c in feat:
    feat_df = pd.get_dummies(properties[c], prefix=c)
    properties = pd.concat([properties, feat_df], axis=1)
    properties.pop(c)


print('preprocess ends ')
train_df = train.merge(properties, how='left', on='parcelid')
print(train_df.shape)

# add statistic feature
print('start feature engineering')
train_df['transactiondate'] = pd.to_datetime(train_df['transactiondate'])
train_df["month"] = train_df.transactiondate.dt.month
train_df["quarter"] = train_df.transactiondate.dt.quarter
traingroupedMonth = train_df.groupby(["month"])["logerror"].mean().to_frame().reset_index()
traingroupedQuarter = train_df.groupby(["quarter"])["logerror"].mean().to_frame().reset_index()
train_df['month_logerror'] = train_df['month'].map(lambda x: round(traingroupedMonth.ix[int(x) - 1]['logerror'], 6))
train_df['quarter_logerror'] = train_df['quarter'].map(
    lambda x: round(traingroupedQuarter.ix[int(x) - 1]['logerror'], 6))
train_df.pop('month')
train_df.pop('quarter')

# drop out ouliers
UP_LIMIT_BODER = 97.5
DOWN_LIMIT_BODER = 2.5
ulimit = np.percentile(train.logerror.values, UP_LIMIT_BODER)
llimit = np.percentile(train.logerror.values, DOWN_LIMIT_BODER)
print('the logerror = %f < %f percent' % (ulimit, UP_LIMIT_BODER))
print('the logerror = %f > %f percent' % (llimit, DOWN_LIMIT_BODER))
train_df = train_df[train_df.logerror >= llimit]
train_df = train_df[train_df.logerror <= ulimit]

# create training set
x_train = train_df.drop(['parcelid', 'logerror', 'transactiondate'], axis=1)
y_train = train_df["logerror"].values.astype(np.float32)
y_mean = np.mean(y_train)
# create test set
x_test = properties.drop(['parcelid'], axis=1)
# standardization
sc = StandardScaler()
x_train = sc.fit_transform(x_train)

print('After removing outliers:')
print('Shape train: {}'.format(x_train.shape))
print('feature engineering end')

# xgboost params
print('start to build model')
xgb_params = {
    'learning_rate': 0.03,
    'max_depth': 5,
    'min_child_weight': 8,
    'silent': 1,
    'subsample': 0.8,
    'colsample_bytree': 0.8,
    'n_estimators': 1000,
    'gamma': 0,
    'objective': 'reg:linear',
    'eval_metric': 'mae',
    #'base_score': y_mean,
}

dtrain = xgb.DMatrix(x_train, y_train)
# cross-validation
cv_result = xgb.cv(xgb_params,
                   dtrain,
                   nfold=5,
                   num_boost_round=1000,
                   early_stopping_rounds=50,
                   verbose_eval=1,
                   show_stdv=False
                   )
num_boost_rounds = len(cv_result)
print(num_boost_rounds)
# train model
model = xgb.train(dict(xgb_params, silent=1), dtrain, num_boost_round=num_boost_rounds)
res = []

for i in range(3):
    x_test['month_logerror'] = round(traingroupedMonth.ix[9 + int(i)]['logerror'], 6)
    x_test['quarter_logerror'] = round(traingroupedQuarter.ix[3]['logerror'], 6)
    test_set = sc.transform(x_test)
    dtest = xgb.DMatrix(test_set)
    pred = model.predict(dtest)
    res.append(pred)

output = pd.DataFrame({'ParcelId': properties['parcelid'].astype(np.int32),
                       '201610': res[0], '201611': res[1], '201612': res[2],
                       '201710': res[0], '201711': res[1], '201712': res[2]})
# set col 'ParceID' to first col
cols = output.columns.tolist()
cols = cols[-1:] + cols[:-1]
output = output[cols]
output.to_csv(utils.file_output, index=False, float_format='%.6f')
# zip
f = zipfile.ZipFile('output.zip', 'w', zipfile.ZIP_DEFLATED)
f.write('output.csv')
