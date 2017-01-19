"""
/sfm-data/collection_set/cf8fcf5ec90a45ff8fcfc92e745e60a2/d54e2b4f31f54b288ae1219b48d64435/2017/01/14/05/183191680d9d4994af4b889fda1e1aa2-20170114052801121-00000-61-7a992d1d0f3f-8000.warc.gz

twitter_stream_warc_iter.py /sfm-data/collection_set/2f235ce78c5046f4be4b1c72bd9d5edd/b0efdaf2605a4585be111225b4cbe2a5/2017/01/14/07/31c5c8d3bbc1473b9ca0200360dc95a1-20170114074446288-00000-76-59e464cef8fd-8000.warc.gz | jq -c '{ sm_type: "tweet", collection_set: "2f235ce78c5046f4be4b1c72bd9d5edd", collection: "b0efdaf2605a4585be111225b4cbe2a5", mongo: "", harvest_type: "twitter_filter", warc: "/sfm-data/collection_set/2f235ce78c5046f4be4b1c72bd9d5edd/b0efdaf2605a4585be111225b4cbe2a5/2017/01/14/07/31c5c8d3bbc1473b9ca0200360dc95a1-20170114074446288-00000-76-59e464cef8fd-8000.warc.gz", id: .id, user_id: .user.id_str, screen_name: .user.screen_name, created_at: .created_at, text: .text, geoip_longitude: .coordinates?.coordinates[0], geoip_latitude: .coordinates?.coordinates[1], user_mentions: [.entities.user_mentions[]?.screen_name], hashtags: [.entities.hashtags[]?.text], urls: [.entities.urls[]?.expanded_url]}' | /opt/logstash/bin/logstash -f stdin.conf

"""

from sfmutils.consumer import BaseConsumer, MqConfig, EXCHANGE
from subprocess import check_output, CalledProcessError
import logging
import argparse
import pymongo
from bson import json_util
import json
import glob
import os, fnmatch

log = logging.getLogger(__name__)

# Not sure how to implementvf dotted field names with `jq`,
# so geoip.<latitude,longitude> was renamed to geoip_<latitude, longitude>.
jq_twtr ="jq -c '{ sm_type: \"tweet\", " \
         "collection_set: \"%(COLLECTION_SET)s\", "\
         "collection: \"%(COLLECTION)s\", "\
         "mongo: \"%(MONGO)s\", harvest_type: \"%(HARVEST_TYPE)s\", " \
         "warc: \"%(WARC)s\", "\
         "id: .id, user_id: .user.id_str, " \
         "screen_name: .user.screen_name, created_at: .created_at, text: .text, " \
         "retweet_count: .retweet_count, favorite_count: .favorite_count, retweeted: .retweeted, " \
         "user_description: .user.description, " \
         "geoip_longitude: .coordinates?.coordinates[0], " \
         "geoip_latitude: .coordinates?.coordinates[1], " \
         "user_mentions: [.entities.user_mentions[]?.screen_name], " \
         "hashtags: [.entities.hashtags[]?.text], " \
         "urls: [.entities.urls[]?.expanded_url]}'"


def get_jq_cmd(harvest_type, collection_set, collection, warc_filepath):

    jq_cmd = jq_twtr % {'HARVEST_TYPE': harvest_type, 
                        'COLLECTION_SET': collection_set,
                        'COLLECTION': collection,
                        'WARC': warc_filepath, 
                        'MONGO': ''}

    if harvest_type in ('twitter_search', 'twitter_user_timeline'):
        iter_type = "twitter_rest_warc_iter.py"
    elif harvest_type in ('twitter_sample', 'twitter_filter'):
        iter_type = "twitter_stream_warc_iter.py"
    elif harvest_type == 'weibo_timeline':
        # override for Weibo
        iter_type = "weibo_warc_iter.py"
        jq_cmd = "jq -c '{ sm_type: \"weibo\", id: .mid, user_id: .user.idstr, " \
                 "screen_name: .user.screen_name, created_at: .created_at, text: .text}'"
    else:
        raise Exception('No iterator for harvest_type = "%s"' % harvest_type)

    return jq_cmd, iter_type


class ElkLoader(BaseConsumer):
    def __init__(self, collection_set_id=None, mq_config=None):
        BaseConsumer.__init__(self, mq_config=mq_config)
        self.collection_set_id = collection_set_id
        if self.collection_set_id:
            log.info("Limiting to collection sets %s", self.collection_set_id)
        else:
            log.info("Not limiting by collection set.")

    def on_message(self):
        log.info(str('------------ ELkLoader -----------'))
        log.info(str(type(self.message)))
        log.info(str(self.message))
        log.info(json.dumps(self.message, indent=2))
        """
        "collection_set": {
            "id": "bdb94ce08ebb49d0ba8a7cdcc1e37ff6"
          }, 
          "harvest": {
            "type": "twitter_filter", 
            "id": "bb02bb5537de4bc3aa138a114013e22d"
          }, 
          "warc": {
            "path": "/sfm-data/collection_set/bdb94ce08ebb49d0ba8a7cdcc1e37ff6/c397f7da7e7a40bdbc89b9df542957ce/2017/01/14/03/bb02bb5537de4bc3aa138a114013e22d-20170114032325624-00000-60-608e249d40a7-8000.warc.gz", 
            "id": "b77a40fb63634800a572a6e22fb51e72", 
            "date_created": "2017-01-13T22:23:26.151674-05:00"
          }, 
          "collection": {
            "id": "c397f7da7e7a40bdbc89b9df542957ce"
          }
        }
        """

        # Message should be WARC created
        warc_filepath = self.message["warc"]["path"]
        collection_set = self.message["collection_set"]["id"]
        collection = self.message["collection"]["id"]
        harvest_type = self.message["harvest"]["type"]

        if self.collection_set_id and self.collection_set_id != collection_set:
            log.info("Skipping %s because it is from a different collection set", warc_filepath)
            return

        jq_cmd, iter_type = get_jq_cmd(harvest_type, collection_set, collection, warc_filepath)

        cmd = "{} {} | {} | /opt/logstash/bin/logstash -f stdin.conf".format(iter_type, warc_filepath, jq_cmd)
        #cmd = "{} {} | /opt/logstash/bin/logstash -f stdin.conf".format(iter_type, warc_filepath)
        log.info('<CMD> ' + cmd)

        try:
            check_output(cmd, shell=True)
            log.info("Loading %s completed.", warc_filepath)
        except CalledProcessError, e:
            log.error("%s returned %s: %s", cmd, e.returncode, e.output)


def find_files(directory, pattern):
    out = []
    for root, dirs, files in os.walk(directory):
        for basename in files:
            if fnmatch.fnmatch(basename, pattern):
                filename = os.path.join(root, basename)
                out.append(filename)
    return sorted(list(set(out)))


def get_mongo_client(ip='10.0.10.31', port=27017):
    "Get a pymongo MongoClient for the localhost."
    return pymongo.MongoClient(ip, port)


def load_mongo_collection(db_str, coll_str, 
                          harvest_type='twitter_filter', 
                          collection_set='',
                          collection='',
                          topn=None):
    """
    collection_set: can be set to link existing MongoDB records to new stream.
    """
    client = get_mongo_client()
    db = client[db_str]
    coll = db[coll_str]

    print('-'*100)
    print('Loading mongodb collection "{}", {:,} records'.format(coll_str, coll.count()))

    jq_cmd = jq_twtr % {'MONGO': '%s.%s' % (db_str, coll_str), 
                        'HARVEST_TYPE': harvest_type,
                        'COLLECTION_SET': collection_set,
                        'COLLECTION': collection,
                        'WARC': ''}

    print('\njq command:')
    print(jq_cmd)

    recs = coll.find()
    js_file = 'tweets.json'

    print('\tdumping to json file')
    if topn > 0:
        recs = recs[:topn]
    with open(js_file, 'w+') as fout:
        for i, rec in enumerate(recs):
            rec['created_at'] = rec['created_at_orig']
            #fout.write(json.dumps(rec, default=json_util.default) + u'\n')
            fout.write(json.dumps(rec) + u'\n')
        print('\twrote {:,} lines'.format(i))
        

    cmd = "cat %s | %s | /opt/logstash/bin/logstash -f stdin.conf " \
          % (js_file, jq_cmd)

    #mongo --quiet dbname --eval 'printjson(db.collection.find().toArray())' 
    print('\nlogstash command: ')
    print(cmd)

    try:
        check_output(cmd, shell=True)
        print('\ncommand ran OK')
    except CalledProcessError, e:
        print("\nerror: %s", e.returncode, e.output)
    finally:
        client.close()

def load_mongos():
    db_str = 'twitter'
    harvest_type = 'twitter_filter'

    colls = ['huntington', 'narcan']
    collection_sets = ['bdb94ce08ebb49d0ba8a7cdcc1e37ff6', 'bdb94ce08ebb49d0ba8a7cdcc1e37ff6']
    collections = ['fb336c5bd9d84251af2d596138df8fbb', 'c397f7da7e7a40bdbc89b9df542957ce']

    for coll, coll_set, coll_id in zip(colls, collection_sets, collections):
        print(coll, coll_set, coll_id)
        load_mongo_collection(db_str, coll, harvest_type=harvest_type,
                              collection_set=coll_set, collection=coll_id)

def load_warcs(topn=None):
    "from sfm_elk_loader import load_warcs; load_warcs()"

    #warc_patt = "/sfm-data/collection_set/*/*/*/*/*/*.warc.gz"
    #files = sorted(glob.glob(warc_patt))

    files = find_files('/sfm-data/collection_set/', '*.warc.gz')

    if len(files) == 0:
        print("found no matches: %s" % warc_patt)
        return
    print("found %i files" % len(files))
    
    if topn > 0 and topn < len(files) - 2:
        files = files[:topn]

    harvest_type = 'twitter_filter'

    for i, warc_filepath in enumerate(files):
        print '-'*100
        print '%i of %i: warc_path: %s' % (i+1, len(files), warc_filepath)

        toks = warc_filepath.split('/')

        collection_set, collection = toks[3], toks[4]

        jq_cmd, iter_type = get_jq_cmd(harvest_type, collection_set, collection, warc_filepath)
        
        cmd = "{} {} | {} | /opt/logstash/bin/logstash -f stdin.conf".format(iter_type, warc_filepath, jq_cmd)
        print('<CMD> ' + cmd)

        try:
            check_output(cmd, shell=True)
            print("Loading %s completed." % warc_filepath)
        except CalledProcessError, e:
            print("%s returned %s: %s", cmd, e.returncode, e.output)



if __name__ == "__main__":
    """
    Called by docker/start.sh
        python sfm_elk_loader.py mq $RABBITMQ_USER $RABBITMQ_PASSWORD elk_loader_$HOSTNAME --debug=$DEBUG $* &
    """
    # Logging
    logging.basicConfig(format='%(asctime)s: %(name)s --> %(message)s', level=logging.DEBUG)

    # Arguments
    parser = argparse.ArgumentParser()
    parser.add_argument("host")
    parser.add_argument("username")
    parser.add_argument("password")
    parser.add_argument("queue")
    parser.add_argument("--collection-set", help="Limit to load to collection set with this collection set id.")
    parser.add_argument("--debug", type=lambda v: v.lower() in ("yes", "true", "t", "1"), nargs="?",
                        default="False", const="True")

    args = parser.parse_args()

    # Logging
    logging.getLogger().setLevel(logging.DEBUG if args.debug else logging.INFO)

    # Adding a queue name that is prefixed with this host. This will allow sending messages directly
    # to this queue. This approach could be generalized so that the queue specific binding is created
    # and the queue name is automatically removed.
    loader = ElkLoader(collection_set_id=args.collection_set,
                       mq_config=MqConfig(args.host, args.username, args.password, EXCHANGE,
                                          {args.queue: ["warc_created", "{}.warc_created".format(args.queue)]}))
    loader.run()

"""
## fail with substring : not found
twitter_stream_warc_iter.py /sfm-data/collection_set/2f235ce78c5046f4be4b1c72bd9d5edd/0da5c49994844899b255c5d7bc27a8bf/2017/01/14/09/WEB-20170114095529443-00000-60~fd8654996a3f~8443.warc.gz | jq -c '{ sm_type: "tweet", collection_set: "2f235ce78c5046f4be4b1c72bd9d5edd", collection: "0da5c49994844899b255c5d7bc27a8bf", mongo: "", harvest_type: "twitter_filter", warc: "/sfm-data/collection_set/2f235ce78c5046f4be4b1c72bd9d5edd/0da5c49994844899b255c5d7bc27a8bf/2017/01/14/09/WEB-20170114095529443-00000-60~fd8654996a3f~8443.warc.gz", id: .id, user_id: .user.id_str, screen_name: .user.screen_name, created_at: .created_at, text: .text, retweet_count: .retweet_count, favorite_count: .favorite_count, retweeted: .retweeted, user_description: .user.description, geoip_longitude: .coordinates?.coordinates[0], geoip_latitude: .coordinates?.coordinates[1], user_mentions: [.entities.user_mentions[]?.screen_name], hashtags: [.entities.hashtags[]?.text], urls: [.entities.urls[]?.expanded_url]}' | /opt/logstash/bin/logstash -f stdin.conf
"""