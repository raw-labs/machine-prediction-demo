from sklearn.neural_network import MLPClassifier
from sklearn.neighbors import KNeighborsClassifier
from sklearn.tree import DecisionTreeClassifier
from sklearn.ensemble import RandomForestClassifier, AdaBoostClassifier
from sklearn.naive_bayes import GaussianNB
from sklearn.discriminant_analysis import QuadraticDiscriminantAnalysis

def machines_train(data, cl, train_test, fail_good):
    classifiers = [
        KNeighborsClassifier(3),
        DecisionTreeClassifier(max_depth=5),
        RandomForestClassifier(max_depth=5, n_estimators=10, max_features=1),
        MLPClassifier(alpha=1, max_iter=1000),
        AdaBoostClassifier(),
        GaussianNB(),
        QuadraticDiscriminantAnalysis()]

    x_good = []
    y_good = []
    x_bad = []
    y_bad = []
    for f in data:
        if f['failure'] == 0:
            x_good.append(f['features'])
            y_good.append(f['failure'])
        else:
            x_bad.append(f['features'])
            y_bad.append(f['failure'])

    n_bad = len(x_bad)
    train_bad = int(n_bad * train_test)
    train_good = int(train_bad * (1-fail_good) / fail_good)

    test_bad = int(n_bad * (1 - train_test))
    test_good = int( test_bad * (1 - fail_good) / fail_good)

    train_x = x_good[:train_good] + x_bad[:train_bad]
    train_y = y_good[:train_good]+ y_bad[:train_bad]

    test_x = x_good[train_good:train_good + test_good] + x_bad[train_bad:]
    test_y = y_good[train_good:train_good + test_good] + y_bad[train_bad:]
    clf = classifiers[cl]
    clf.fit(train_x, train_y)
    predict = clf.predict(test_x)

    results = {
        'used': {'training': len(train_x), 'testing': len(test_x)},
        'good': {'total': 0, 'correct': 0},
        'failure': {'total': 0, 'correct': 0}
    }

    for n, result in enumerate(test_y):
        v = 'good' if result == 0 else 'failure'
        results[v]['total'] += 1
        if result == predict[n]:
            results[v]['correct'] += 1
    return results