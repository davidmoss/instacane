#!/usr/bin/env python
# -*- coding: UTF-8 -*-

"""
load.py

Created by Chris Ackermann + Peter Ng on 2011-08-25.
Copyright (c) 2011 Chris Ackermann + Peter Ng. All rights reserved.

"""

import ConfigParser
import json
import datetime
import urlparse
import memcache
import pymongo
import requests
from instacane.insta_gram import Instagram
from instacane.twit_ter import Twitter
from instacane.location import get_location_gmaps


class MediaLoader(object):

    instagram_domains = ['instagr.am', 'instagram.com']

    def __init__(self, *args, **kwargs):
        self.twitter = Twitter()
        self.instagram = Instagram()
        self.config = self._get_config()
        self.blocklist = self._get_block_list()
        self.memcache = memcache.Client(
            [self.config.get('cache', 'hostname')], debug=1)
        self.memcache.set('testing', 'connection')
        self.memcache.delete('testing')
        self.mongo = pymongo.Connection(
            self.config.get('db', 'hostname'))

    def load_instacane_data(self):
        items = self._search_keywords_on_twitter()
        output_data = []
        for item in items:
            tweet_link = ""
            instagram_link = ""
            if len(item.urls) > 0:
                tweet_link = self._clean_url(item.urls[0].url)
                instagram_link = self._clean_url(item.urls[0].expanded_url)

            if not self._is_link_good(instagram_link):
                print("Instagram link looks bad, skipping... %s" % instagram_link)
                continue

            twitter_text = item.text
            twitter_text = twitter_text.replace(tweet_link, '').strip()

            twitter_sn = item.user.screen_name
            if twitter_sn in self.blocklist:
                print("Filtering out twitter user : %s, skipping..." %
                    twitter_sn)
                continue

            try:
                img_data = self._get_instagram_image_data(
                    instagram_link)
            except Exception as reason:
                print("Unable to fetch image metadata: error = %s" % reason)
                continue

            if img_data['direct_img_url'].find('.mp4') != -1:
                print("Media is a video.  Skipping...")
                continue

            photo_object = {
                'direct_img_url': img_data['direct_img_url'],
                'instagram_url': instagram_link,
                'geolocation': img_data['geolocation'],
                'twitter_username': twitter_sn,
                'instagram_username': img_data['instagram_sn']
            }
            if img_data['instagram_caption'] is None:
                photo_object['caption'] = twitter_text
            else:
                photo_object['caption'] = img_data['instagram_caption']

            print("Adding item w caption : %s : %s" % (photo_object['caption'], item.id))
            output_data.append(photo_object)

        ts = datetime.datetime.utcnow()
        self._save_to_cache(ts, output_data)
        self._save_to_db(ts, output_data)

    def _get_instagram_image_data(self, instagram_link):
        try:
            img_data = self.instagram.get_image_metadata(
                instagram_link)
        except Exception as reason:
            print("Unable to fetch image metadata: error = %s" % reason)
            raise

        oembed_data = img_data['oembed']
        if oembed_data is None:
            raise RuntimeError('No image data found...')

        image_data = {
            'instagram_sn': oembed_data['author_name'],
            'instagram_caption': oembed_data['title'],
            'direct_img_url': oembed_data['url'],
            'geolocation': ""
        }
        media_data = img_data['media']
        if media_data is not None:
            instagram_location = None
            if hasattr(media_data, 'location'):
                instagram_location = media_data.location
            image_data['geolocation'] = self._fetch_geolocation(
                instagram_location)

        return image_data

    def _is_link_good(self, url):
        if url is None or url == '':
            return False
        response = requests.head(url)
        if response.status_code != 200:
            return False
        return True

    def _clean_url(self, url):
        parsed_url = urlparse.urlparse(url)
        return "%s://%s%s%s" % (parsed_url.scheme, parsed_url.netloc.lower(),
            parsed_url.path, parsed_url.params)

    def _fetch_geolocation(self, instagram_location):
        formatted_location = ""
        if instagram_location is not None:
            try:
                formatted_location = get_location_gmaps(
                    instagram_location.point.latitude,
                    instagram_location.point.longitude)
            except Exception as reason:
                print("Unable to get location data : error = %s" % reason)
        return formatted_location

    def _save_to_cache(self, ts, data):
        json_str = json.dumps(data)
        date = ts.strftime("%A, %B %d, %Y %I:%M %p")
        self.memcache.set("latest_photos", json_str)
        self.memcache.set("latest_ts", date)
        print("Saved to cache.")

    def _save_to_db(self, ts, data):
        self.mongo.instacane.page_data.insert({
            "ts" : ts,
            "data" : data
        })
        print("Saved to db.")

    def _search_keywords_on_twitter(self):
        domains = self._get_domains_query()
        kws_hashtags = self._get_keywords_hashtags_query()
        query = "%s %s" % (kws_hashtags, domains)
        print("Twitter query is '%s'" % query)
        return self.twitter.search(query)

    def _get_block_list(self):
        block_list = self.config.get('userlist', 'block')
        block_list = block_list.split(',')
        block_list = [user.strip() for user in block_list]
        return block_list

    def _get_keywords_hashtags_query(self):
        query_items = []
        keywords = self.config.get('search', 'keywords')
        if keywords != '':
            keywords = keywords.split(',')
            for keyword in keywords:
                query_items.append(keyword.strip())

        hashtags = self.config.get('search', 'hashtags')
        if hashtags != '':
            hashtags = hashtags.split(',')
            for hashtag in hashtags:
                query_items.append("#%s" % hashtag.strip())

        return ' OR '.join(query_items)

    def _get_domains_query(self):
        return ' OR '.join(self.instagram_domains)

    def _get_config(self):
        config = ConfigParser.ConfigParser()
        readfiles = config.read('instacane.cfg')
        if len(readfiles) == 1:
            return config
        raise RuntimeError('Error finding instacane.cfg.  Where is it??')
