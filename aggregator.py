#!/usr/bin/env python
# -*- encoding: utf-8 -*-

import itertools
import collections
import types
import csv
from cStringIO import StringIO
from datetime import date
from _abcoll import Mapping

#################################################
## Classes

Total = collections.namedtuple('Total', ['count','amount'])

class Aggregator(dict):
    # This class simplifies taking an aggregate count and volume from a list of financial transactions, supporting access to multiple views on the completed sums by sets of keys.
	
    '''Create a miniature database-like object to quickly see totals for a given set of keys.
    
    :param: fieldnames: initial list of fields to use for labelling keys by their type.
    '''

    def __init__(self, fieldnames, *args, **kwargs):
        self._fields = tuple(fieldnames)
        self._keywrapper = collections.namedtuple('Key', fieldnames, **kwargs)
        for key in args:
            self[tuple(key)] = Total(0, 0.0)

    def __repr__(self):
        return '\n'.join('%s: %s' % (k,v) for k,v in self.iteritems())

    def __setitem__(self, key, value):
        key = tuple(self._keywrapper(*key)._asdict().values()) # fail if key can't match fields
        super(Aggregator, self).__setitem__(key, sumTotals(value))

    def __iadd__(self, other):
        self.update(other)
        return self

    def __add__(self, other):
        if not isinstance(other, Aggregator):
            return NotImplemented
        if self._fields != other._fields:
            raise ValueError("Mismatch between fields!\n  Original: %s\n  Applying: %s\n" % (self._fields, other._fields))
        result = Aggregator(self._fields)
        for key, total in itertools.chain(*(o.iteritems() for o in (self, other))):
            key = tuple(self._keywrapper(*key)._asdict().values()) # fail if key can't match fields
            result.update({key: total})
        return result

    def update(self, *args, **kwargs):
        if args and len(args) > 1:
            raise TypeError('expected at most 1 arguments, got %d' % len(args))
        iterable = args[0] if args else None
        if iterable is not None:
            if isinstance(iterable, Mapping):
                for k, v in iterable.iteritems():
                    key = tuple(self._keywrapper(*k)._asdict().values()) # fail if key can't match fields
                    if self.get(key):
                        self[key] = sumTotals(self[key], v)
                    else:
                        self[key] = sumTotals(v)
            else:
                raise TypeError('expected a mapping between keys and values, got %s' % type(iterable))
        if kwargs:
            self.update(kwargs)

    def merge(self, other):
        '''Put together two arbitrary aggregators, supplying None for fieldkey
           values where the fields don't match.'''
        if not isinstance(other, Aggregator):
            return NotImplemented
        # Although we can't guarantee field order, this shouldn't matter to us.
        fields = tuple(set(other._fields).union(set(self._fields)))
        result = Aggregator(fields)
        for key, total in itertools.chain(*(o.iteritems() for o in (self, other))):
            result_key = list(None for i in fields)
            for k in key:
                result_key[fields.index(key._fields[key.index(k)])] = k
            key = tuple(result_key)
            result.update({key: total})
        return result

    def iteritems(self):
        for k, v in super(Aggregator, self).iteritems():
            yield self._keywrapper(*k), v

    def items(self):
        return [(self._keywrapper(*k), v) for k, v in super(Aggregator, self).items()]

    def iterfieldkeys(self, field):
        index = self._fields.index(field)
        for key in self.iterkeys():
            yield key[index]

    def fieldkeys(self, field):
        index = self._fields.index(field)
        return set( fk[index] for fk in self.keys() )

    def filter(self, *args):
        filtered_copy = Aggregator(self._fields)
        for k in args:
            found = [key for key in self if k in key]
            for key in found:
                filtered_copy[key] = self[key]
        return filtered_copy

    def collapse(self, collapse_field):
        '''Remove a sub-key element and merge values lacking the key, returning a new Aggregator.'''
        collapse_index = self._fields.index(collapse_field)
        fields = list(self._fields)
        fields.remove(collapse_field)
        collapsed_copy = Aggregator(fields)
        for key, value in self.iteritems():
            key = list(key)
            toss = key.pop(collapse_index)
            key = tuple(key)
            if collapsed_copy.get(key):
                collapsed_copy[key] = sumTotals(collapsed_copy[key], value)
            else:
                collapsed_copy[key] = sumTotals(value)
        return collapsed_copy

    def value_sorted(self, by_count=False, reverse=False):
        return sorted(self.iteritems(), key=lambda (k,v): (v.count, v.amount) if by_count else (v.amount, v.count), reverse=reverse)

    def field_sorted(self, *field_keys, **kwargs):
        r = kwargs.get('reverse') or False
        return sorted(self.iteritems(), key=lambda (k,v): [self._keywrapper(*k)._asdict[fk] for fk in field_keys], reverse=r)

    def getcsv(self, *sort_keys, **kwargs):
        csv_fd = StringIO()
        r = kwargs.pop('reverse') if kwargs.get('reverse') else False
        # leaving this open to **kwargs for passing in alternate dialects
        cw = csv.writer(csv_fd, **kwargs)
        cw.writerow(self._fields + ('count', 'amount'))
        for pair in self.field_sorted(*sort_keys, reverse=r):
            # each row is a (Key, Total) pair.
            cw.writerow([i._asdict.values() for i in pair])
        csv_fd.seek(0)
        return csv_fd


#################################################
##                Functions
#################################################

def sumTotals(*t):
    count, amount = 0, 0.0
    for total in t:
        if isinstance(total, (int, float)):
            count += 1
            amount += float(total)
        else:
            count += int(total[0])
            amount += float(total[1])
    return Total(count, amount)


def getComplexCountFromSqlQuery(query, cursor, keylist):
    SqlMap = collections.Counter()
    cursor.execute(query)
    key_indices = dict( (cursor.fieldnames().index(k), k) for k in keylist)
    for row in cursor.fetchall():
        count = None
        key = keylist[:]
        for i, value in enumerate(row):
            if i in key_indices:
                key[keylist.index(key_indices[i])] = value
                continue
            count = int(value) if type(value) in (int,long) or (type(value) in (str,unicode) and value.isdigit()) else float(value)
        SqlMap[tuple(key)] = count
    return SqlMap

def getSetDictFromSqlQuery(query, cursor, keylist):
    SqlMap = dict()
    cursor.execute(query)
    key_indices = dict( (cursor.fieldnames().index(k), k) for k in keylist)
    for row in cursor.fetchall():
        item = None
        key = keylist[:]
        for i, value in enumerate(row):
            if i in key_indices:
                key[keylist.index(key_indices[i])] = value
                continue
            item = set([value]) if type(value) is not set else value
        if not SqlMap.get(tuple(key)):
            SqlMap[tuple(key)] = item
        else:
            SqlMap[tuple(key)].update(item)
    return SqlMap

def getAggregatesFromSqlQuery(query, cursor, keylist):
    SqlMap = Aggregator(keylist)
    cursor.execute(query)
    key_indices = dict( (cursor.fieldnames().index(k), k) for k in keylist)
    for row in cursor.fetchall():
        count, amount = None, None
        key = keylist[:]
        for i, value in enumerate(row):
            if i in key_indices:
                key[keylist.index(key_indices[i])] = value
                continue
            # assume count is followed by amount, always
            if count:
                amount = float(value)
            else:
                count = int(value)
        SqlMap[tuple(key)] = Total(count, amount)
    return SqlMap


if __name__ == '__main__':
    import random
    agg = Aggregator(['field1', 'field2', 'field3'])

    ccy = ('EUR', 'GBP', 'PLN', 'USD')
    land = ('de', 'es', 'fr', 'it', 'nl', 'pt')
    method = ('pos','atm')

    for n in xrange(20):
        f1 = ccy[random.randrange(0,len(ccy))]
        f2 = land[random.randrange(0,len(land))]
        f3 = method[random.randrange(0,len(method))]
        agg.update({(f1,f2,f3): n*float('%01.2f' % random.random())})

    agg1 = agg.filter('EUR').collapse('field2')
    agg2 = agg.filter('USD').collapse('field1')

    print("Agg1")
    print(agg1)
    print("\n")
    print("Agg2")
    print(agg2)
    print("\n")

    print("Merge Test:")
    print(agg1.merge(agg2))
    print("\n")

    print("Add Test (agg1 + agg1):")
    print(agg1 + agg1)
    print("\n")

    for k, v in agg1.iteritems():
        print("%s: %s" % (k, v))
    print("\n")

    print(agg2.items())
    print("\n")

    print("__iadd__ Test (agg1 + agg2):")
    print("note: update does not respect fieldkeys, only the number of fieldkeys")
    agg1 += agg2
    print(agg1)
    print("\n")

