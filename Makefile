ARCHES := x86
S9PK_MK := node_modules/@start9labs/start-sdk/s9pk.mk
$(S9PK_MK): package.json
	npm install
include $(S9PK_MK)

# start-cli pack loads ./javascript/index.js; list-ingredients may omit it.
$(BASE_NAME)_%.s9pk: javascript/index.js
$(BASE_NAME).s9pk: javascript/index.js
