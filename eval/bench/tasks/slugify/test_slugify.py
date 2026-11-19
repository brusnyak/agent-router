from slugger import slugify
def test_basic(): assert slugify("Hello, World!") == "hello-world"
def test_accents(): assert slugify("  Crème Brûlée  ") == "creme-brulee"
def test_runs(): assert slugify("a--b__c") == "a-b-c"
def test_empty(): assert slugify("!!!") == ""
def test_umlaut(): assert slugify("Ünï") == "uni"
