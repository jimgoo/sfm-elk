curl -H 'Content-Type: application/json' -X PUT -d $1
{
  "mappings": {
    "my_type": {
      "properties": {
        "geo_location": {
          "type": "geo_point"
        }
      }
    }
  }
}