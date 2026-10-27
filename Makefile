ARCHES := x86
S9PK_MK := node_modules/@start9labs/start-sdk/s9pk.mk
$(S9PK_MK): package.json
	npm install
include $(S9PK_MK)

# list-ingredients omits runtime/. An explicit rule merges into the pack recipe.
# A second pattern rule does not.
$(BASE_NAME)_x86_64.s9pk: $(wildcard runtime/*.py)
$(BASE_NAME)_aarch64.s9pk: $(wildcard runtime/*.py)
$(BASE_NAME).s9pk: $(wildcard runtime/*.py)
