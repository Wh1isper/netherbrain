from netherbrain.im_gateway.gateway import IMGateway


def test_im_gateway_init():
    gw = IMGateway(runtime_url="http://localhost:8000")
    assert gw.runtime_url == "http://localhost:8000"
