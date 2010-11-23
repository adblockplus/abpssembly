# coding: utf-8

import os, sys, re, marshal
from time import time
from sitescripts.utils import get_config, setupStderr
from sitescripts.templateFilters import formatmime
from sitescripts.reports.utils import mailDigest, calculateReportSecret
import sitescripts.subscriptions.subscriptionParser as subscriptionParser

def loadSubscriptions():
  global interval

  subscriptions = subscriptionParser.readSubscriptions()

  results = {}
  resultList = []
  for subscription in subscriptions.values():
    if subscription.digest == 'daily' and interval == 'week':
      continue
    if subscription.digest == 'weekly' and interval == 'day':
      continue

    for [title, url, complete] in subscription.variants:
      results[url] = subscription
    resultList.append(subscription)
  return (results, resultList)

def scanReports(dir, result = []):
  global fakeSubscription, interval, subscriptions, startTime

  for file in os.listdir(dir):
    filePath = os.path.join(dir, file)
    if os.path.isdir(filePath):
      scanReports(filePath, result)
    elif file.endswith('.dump'):
      handle = open(filePath, 'rb')
      reportData = marshal.load(handle)
      handle.close()

      if reportData.get('time', 0) < startTime:
        continue

      recipients = []

      # Send type "other" to fake subscription - daily reports
      if interval != 'week':
        recipients.append(fakeSubscription)

      if reportData.get('type', 'unknown') == 'false positive' or reportData.get('type', 'unknown') == 'false negative':
        recipients = []
        for subscription in reportData.get('subscriptions', []):
          if subscription.get('id', 'unknown') in subscriptions:
            recipients.append(subscriptions[subscription.get('id', 'unknown')])

      if len(recipients) == 0:
        continue

      matchSubscriptions = []
      for filter in reportData.get('filters', []):
        for url in filter.get('subscriptions', []):
          if url in subscriptions:
            matchSubscriptions.append(subscriptions[url])

      guid = re.sub(r'\.dump$', r'', file)
      report = {
        'url': get_config().get('reports', 'urlRoot') + guid + '#secret=' + calculateReportSecret(guid),
        'weight': calculateReportWeight(reportData),
        'site': reportData.get('siteName', 'unknown'),
        'subscriptions': recipients,
        'comment': re.sub(r'[\x00-\x20]', r' ', reportData.get('comment', '')),
        'type': reportData.get('type', 'unknown'),
        'numSubscriptions': len(reportData.get('subscriptions', [])),
        'matchSubscriptions': matchSubscriptions,
      }
      result.append(report)
  return result

def sendNotifications(reports):
  global subscriptionList

  for subscription in subscriptionList:
    selectedReports = filter(lambda report: subscription in report['subscriptions'], reports)
    if len(selectedReports) == 0:
      continue

    groups = {}
    for report in selectedReports:
      if report['site'] in groups:
        groups[report['site']]['reports'].append(report)
        groups[report['site']]['weight'] += report['weight']
      else:
        groups[report['site']] = {'name': report['site'], 'reports': [report], 'weight': report['weight'], 'dumpAll': False}

    miscGroup = {'name': 'Misc', 'reports': [], 'weight': None, 'dumpAll': True}
    for (site, group) in groups.items():
      if len(group['reports']) == 1:
        miscGroup['reports'].append(group['reports'][0])
        del groups[site]

    if len(miscGroup['reports']) > 0:
      groups[miscGroup['name']] = miscGroup

    groups = groups.values()
    groups.sort(lambda a,b: -cmp(a['weight'], b['weight']))
    for group in groups:
      group['reports'].sort(lambda a,b: -cmp(a['weight'], b['weight']))

    sendMail(subscription, groups)

def sendMail(subscription, groups):
  if hasattr(subscription, 'email'):
    email = subscription.email
  else:
    email = subscription['email']

  match = re.match(r'^(.*?)\s*<\s*([\x21-x7F]+)\s*>\s*$', email)
  if match:
    email = formatmime(match.group(1)) + ' <' + match.group(2) + '>'

  mailDigest({'email': email, 'subscription': subscription, 'groups': groups})

def calculateReportWeight(reportData):
  global currentTime, startTime

  weight = 1.0
  if reportData.get('type', 'unknown') == 'false positive' or reportData.get('type', 'unknown') == 'false negative':
    weight /= len(reportData.get('subscriptions', []))
  if 'screenshot' in reportData:
    weight += 0.3
  if len(reportData.get('knownIssues', [])) > 0:
    weight -= 0.3
  if re.search(r'\btest\b', reportData.get('comment', ''), re.IGNORECASE):
    weight -= 0.5
  elif re.search(r'\S', reportData.get('comment', '')):
    weight += 0.5

  weight += (reportData.get('time', 0) - startTime) / (currentTime - startTime) * 0.2
  return weight

if __name__ == '__main__':
  setupStderr()

  if len(sys.argv) < 2:
    raise Exception('No interval specified')

  interval = sys.argv[1]
  if not (interval in ['all', 'week', 'day']):
    raise Exception('Invalid interval')

  currentTime = time()
  startTime = 0
  if interval == 'week':
    startTime = currentTime - 7*24*60*60
  elif interval == 'day':
    startTime = currentTime - 24*60*60

  fakeSubscription = {'url': 'https://fake.adblockplus.org', 'name': get_config().get('reports', 'defaultSubscriptionName'), 'email': get_config().get('reports', 'defaultSubscriptionRecipient')}
  (subscriptions, subscriptionList) = loadSubscriptions()
  subscriptionList.append(fakeSubscription)
  reports = scanReports(get_config().get('reports', 'dataPath'))
  sendNotifications(reports)