# import pytest
import os
import string
import random
import copy
import json
import pytest
import warnings
import jsonschema
import numpy as np
from ai2thor.controller import Controller
from ai2thor.tests.constants import TESTS_DATA_DIR, TEST_SCENE
from ai2thor.wsgi_server import WsgiServer
from ai2thor.fifo_server import FifoServer
from PIL import ImageChops, ImageFilter, Image
import glob

# Defining const classes to lessen the possibility of a misspelled key
class Actions:
    AddThirdPartyCamera = "AddThirdPartyCamera"
    UpdateThirdPartyCamera = "UpdateThirdPartyCamera"


class MultiAgentMetadata:
    thirdPartyCameras = "thirdPartyCameras"


class ThirdPartyCameraMetadata:
    position = "position"
    rotation = "rotation"
    fieldOfView = "fieldOfView"


def build_controller(**args):
    default_args = dict(scene=TEST_SCENE, local_build=True)
    default_args.update(args)
    # during a ci-build we will get a warning that we are using a commit_id for the
    # build instead of 'local'
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        c = Controller(**default_args)

    # used for resetting
    c._original_initialization_parameters = c.initialization_parameters
    return c


_wsgi_controller = build_controller(server_class=WsgiServer)
_fifo_controller = build_controller(server_class=FifoServer)
_stochastic_controller = build_controller(agentControllerType="stochastic")


def skip_reset(controller):
    # setting attribute on the last event so we can tell if the
    # controller gets used since last event will change after each step
    controller.last_event._pytest_skip_reset = True


# resetting on each use so that each tests works with
# the scene in a pristine state
def reset_controller(controller):
    controller.initialization_parameters = copy.deepcopy(
        controller._original_initialization_parameters
    )
    if not hasattr(controller.last_event, "_pytest_skip_reset"):
        controller.reset(TEST_SCENE)
        skip_reset(controller)

    return controller


@pytest.fixture
def wsgi_controller():
    return reset_controller(_wsgi_controller)


@pytest.fixture
def stochastic_controller():
    return reset_controller(_stochastic_controller)


@pytest.fixture
def fifo_controller():
    return reset_controller(_fifo_controller)


fifo_wsgi = [_fifo_controller, _wsgi_controller]
fifo_wsgi_stoch = [_fifo_controller, _wsgi_controller, _stochastic_controller]

BASE_FP28_POSITION = dict(x=-1.5, z=-1.5, y=0.901,)
BASE_FP28_LOCATION = dict(
    **BASE_FP28_POSITION, rotation={"x": 0, "y": 0, "z": 0}, horizon=0, standing=True,
)


def teleport_to_base_location(controller: Controller):
    assert controller.last_event.metadata["sceneName"] == TEST_SCENE

    controller.step("TeleportFull", **BASE_FP28_LOCATION)
    assert controller.last_event.metadata["lastActionSuccess"]


def setup_function(function):
    for c in [_fifo_controller, _wsgi_controller, _stochastic_controller]:
        reset_controller(c)


def teardown_module(module):
    _wsgi_controller.stop()
    _fifo_controller.stop()
    _stochastic_controller.stop()


def assert_near(point1, point2, error_message=""):
    assert point1.keys() == point2.keys(), error_message + "Keys mismatch."
    for k in point1.keys():
        assert abs(point1[k] - point2[k]) < 1e-3, (
            error_message + f"for {k} key, {point1[k]} != {point2[k]}"
        )


def test_stochastic_controller(stochastic_controller):
    stochastic_controller.reset(TEST_SCENE)
    assert stochastic_controller.last_event.metadata["lastActionSuccess"]


# Issue #514 found that the thirdPartyCamera image code was causing multi-agents to end
# up with the same frame
def test_multi_agent_with_third_party_camera(fifo_controller):
    fifo_controller.reset(TEST_SCENE, agentCount=2)
    assert not np.all(
        fifo_controller.last_event.events[1].frame
        == fifo_controller.last_event.events[0].frame
    )
    event = fifo_controller.step(
        dict(
            action="AddThirdPartyCamera",
            rotation=dict(x=0, y=0, z=90),
            position=dict(x=-1.0, z=-2.0, y=1.0),
        )
    )
    assert not np.all(
        fifo_controller.last_event.events[1].frame
        == fifo_controller.last_event.events[0].frame
    )


# Issue #526 thirdPartyCamera hanging without correct keys in FifoServer FormMap
def test_third_party_camera_with_image_synthesis(fifo_controller):
    fifo_controller.reset(
        TEST_SCENE,
        renderInstanceSegmentation=True,
        renderDepthImage=True,
        renderSemanticSegmentation=True,
    )

    event = fifo_controller.step(
        dict(
            action="AddThirdPartyCamera",
            rotation=dict(x=0, y=0, z=90),
            position=dict(x=-1.0, z=-2.0, y=1.0),
        )
    )
    assert len(event.third_party_depth_frames) == 1
    assert len(event.third_party_semantic_segmentation_frames) == 1
    assert len(event.third_party_camera_frames) == 1
    assert len(event.third_party_instance_segmentation_frames) == 1


def test_rectangle_aspect(fifo_controller):

    fifo_controller.reset(TEST_SCENE, width=600, height=300)
    event = fifo_controller.step(dict(action="Initialize", gridSize=0.25))
    assert event.frame.shape == (300, 600, 3)


def test_small_aspect(fifo_controller):
    fifo_controller.reset(TEST_SCENE, width=128, height=64)
    event = fifo_controller.step(dict(action="Initialize", gridSize=0.25))
    assert event.frame.shape == (64, 128, 3)


def test_bot_deprecation(fifo_controller):
    fifo_controller.reset(TEST_SCENE, agentMode="bot")
    assert (
        fifo_controller.initialization_parameters["agentMode"].lower() == "locobot"
    ), "bot should alias to locobot!"


def test_deprecated_segmentation_params(fifo_controller):
    # renderObjectImage has been renamed to renderInstanceSegmentation
    # renderClassImage has been renamed to renderSemanticSegmentation

    fifo_controller.reset(
        TEST_SCENE, renderObjectImage=True, renderClassImage=True,
    )
    event = fifo_controller.last_event
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", category=DeprecationWarning)
        assert event.class_segmentation_frame is event.semantic_segmentation_frame
        assert event.semantic_segmentation_frame is not None
        assert (
            event.instance_segmentation_frame is not None
        ), "renderObjectImage should still render instance_segmentation_frame"


def test_deprecated_segmentation_params2(fifo_controller):
    # renderObjectImage has been renamed to renderInstanceSegmentation
    # renderClassImage has been renamed to renderSemanticSegmentation

    fifo_controller.reset(
        TEST_SCENE, renderSemanticSegmentation=True, renderInstanceSegmentation=True,
    )
    event = fifo_controller.last_event

    with warnings.catch_warnings():
        warnings.simplefilter("ignore", category=DeprecationWarning)
        assert event.class_segmentation_frame is event.semantic_segmentation_frame
        assert event.semantic_segmentation_frame is not None
        assert (
            event.instance_segmentation_frame is not None
        ), "renderObjectImage should still render instance_segmentation_frame"


def test_reset(fifo_controller):
    width = 520
    height = 310
    event = fifo_controller.reset(
        scene=TEST_SCENE, width=width, height=height, renderDepthImage=True
    )
    assert event.frame.shape == (height, width, 3), "RGB frame dimensions are wrong!"
    assert event.depth_frame is not None, "depth frame should have rendered!"
    assert event.depth_frame.shape == (
        height,
        width,
    ), "depth frame dimensions are wrong!"

    width = 300
    height = 300
    event = fifo_controller.reset(
        scene=TEST_SCENE, width=width, height=height, renderDepthImage=False
    )
    assert event.depth_frame is None, "depth frame shouldn't have rendered!"
    assert event.frame.shape == (height, width, 3), "RGB frame dimensions are wrong!"


def test_fast_emit(fifo_controller):
    event = fifo_controller.step(dict(action="RotateRight"))
    event_fast_emit = fifo_controller.step(dict(action="TestFastEmit", rvalue="foo"))
    event_no_fast_emit = fifo_controller.step(dict(action="LookUp"))
    event_no_fast_emit_2 = fifo_controller.step(dict(action="RotateRight"))

    assert event.metadata["actionReturn"] is None
    assert event_fast_emit.metadata["actionReturn"] == "foo"
    assert id(event.metadata["objects"]) == id(event_fast_emit.metadata["objects"])
    assert id(event.metadata["objects"]) != id(event_no_fast_emit.metadata["objects"])
    assert id(event_no_fast_emit_2.metadata["objects"]) != id(
        event_no_fast_emit.metadata["objects"]
    )


def test_fifo_large_input(fifo_controller):
    random_string = "".join(
        random.choice(string.ascii_letters) for i in range(1024 * 16)
    )
    event = fifo_controller.step(
        dict(action="TestActionReflectParam", rvalue=random_string)
    )
    assert event.metadata["actionReturn"] == random_string


def test_fast_emit_disabled(fifo_controller):
    slow_controller = fifo_controller
    slow_controller.reset(TEST_SCENE, fastActionEmit=False)
    event = slow_controller.step(dict(action="RotateRight"))
    event_fast_emit = slow_controller.step(dict(action="TestFastEmit", rvalue="foo"))
    # assert that when actionFastEmit is off that the objects are different
    assert id(event.metadata["objects"]) != id(event_fast_emit.metadata["objects"])


@pytest.mark.parametrize("controller", fifo_wsgi)
def test_lookdown(controller):
    e = controller.step(dict(action="RotateLook", rotation=0, horizon=0))
    position = controller.last_event.metadata["agent"]["position"]
    horizon = controller.last_event.metadata["agent"]["cameraHorizon"]
    assert horizon == 0.0
    e = controller.step(dict(action="LookDown"))
    assert e.metadata["agent"]["position"] == position
    assert round(e.metadata["agent"]["cameraHorizon"]) == 30
    assert e.metadata["agent"]["rotation"] == dict(x=0, y=0, z=0)
    e = controller.step(dict(action="LookDown"))
    assert round(e.metadata["agent"]["cameraHorizon"]) == 60
    e = controller.step(dict(action="LookDown"))
    assert round(e.metadata["agent"]["cameraHorizon"]) == 60


@pytest.mark.parametrize("controller", fifo_wsgi)
def test_no_leak_params(controller):

    action = dict(action="RotateLook", rotation=0, horizon=0)
    e = controller.step(action)
    assert "sequenceId" not in action


@pytest.mark.parametrize("controller", fifo_wsgi)
def test_target_invocation_exception(controller):
    # TargetInvocationException is raised when short circuiting failures occur
    # on the Unity side. It often occurs when invalid arguments are used.
    event = controller.step("OpenObject", x=1.5, y=0.5)
    assert not event.metadata["lastActionSuccess"], "OpenObject(x > 1) should fail."
    assert event.metadata[
        "errorMessage"
    ], "errorMessage should not be empty when OpenObject(x > 1)."


@pytest.mark.parametrize("controller", fifo_wsgi_stoch)
def test_lookup(controller):

    e = controller.step(dict(action="RotateLook", rotation=0, horizon=0))
    position = controller.last_event.metadata["agent"]["position"]
    horizon = controller.last_event.metadata["agent"]["cameraHorizon"]
    assert horizon == 0.0
    e = controller.step(dict(action="LookUp"))
    assert e.metadata["agent"]["position"] == position
    assert e.metadata["agent"]["cameraHorizon"] == -30.0
    assert e.metadata["agent"]["rotation"] == dict(x=0, y=0, z=0)
    e = controller.step(dict(action="LookUp"))
    assert e.metadata["agent"]["cameraHorizon"] == -30.0


@pytest.mark.parametrize("controller", fifo_wsgi)
def test_rotate_left(controller):

    e = controller.step(dict(action="RotateLook", rotation=0, horizon=0))
    position = controller.last_event.metadata["agent"]["position"]
    rotation = controller.last_event.metadata["agent"]["rotation"]
    assert rotation == dict(x=0, y=0, z=0)
    horizon = controller.last_event.metadata["agent"]["cameraHorizon"]
    e = controller.step(dict(action="RotateLeft"))
    assert e.metadata["agent"]["position"] == position
    assert e.metadata["agent"]["cameraHorizon"] == horizon
    assert e.metadata["agent"]["rotation"]["y"] == 270.0
    assert e.metadata["agent"]["rotation"]["x"] == 0.0
    assert e.metadata["agent"]["rotation"]["z"] == 0.0


@pytest.mark.parametrize("controller", fifo_wsgi)
def test_simobj_filter(controller):

    objects = controller.last_event.metadata["objects"]
    unfiltered_object_ids = sorted([o["objectId"] for o in objects])
    filter_object_ids = sorted([o["objectId"] for o in objects[0:3]])
    e = controller.step(dict(action="SetObjectFilter", objectIds=filter_object_ids))
    assert len(e.metadata["objects"]) == len(filter_object_ids)
    filtered_object_ids = sorted([o["objectId"] for o in e.metadata["objects"]])
    assert filtered_object_ids == filter_object_ids

    e = controller.step(dict(action="SetObjectFilter", objectIds=[]))
    assert len(e.metadata["objects"]) == 0

    e = controller.step(dict(action="ResetObjectFilter"))
    reset_filtered_object_ids = sorted([o["objectId"] for o in e.metadata["objects"]])
    assert unfiltered_object_ids == reset_filtered_object_ids


@pytest.mark.parametrize("controller", fifo_wsgi)
def test_add_third_party_camera(controller):
    expectedPosition = dict(x=1.2, y=2.3, z=3.4)
    expectedRotation = dict(x=30, y=40, z=50)
    expectedFieldOfView = 45.0
    assert (
        len(controller.last_event.metadata[MultiAgentMetadata.thirdPartyCameras]) == 0
    ), "there should be 0 cameras"

    e = controller.step(
        dict(
            action=Actions.AddThirdPartyCamera,
            position=expectedPosition,
            rotation=expectedRotation,
            fieldOfView=expectedFieldOfView,
        )
    )
    assert (
        len(e.metadata[MultiAgentMetadata.thirdPartyCameras]) == 1
    ), "there should be 1 camera"
    camera = e.metadata[MultiAgentMetadata.thirdPartyCameras][0]
    assert_near(
        camera[ThirdPartyCameraMetadata.position],
        expectedPosition,
        "initial position should have been set",
    )
    assert_near(
        camera[ThirdPartyCameraMetadata.rotation],
        expectedRotation,
        "initial rotation should have been set",
    )
    assert (
        camera[ThirdPartyCameraMetadata.fieldOfView] == expectedFieldOfView
    ), "initial fieldOfView should have been set"

    # expects position to be a Vector3, should fail!
    event = controller.step(
        action="AddThirdPartyCamera", position=5, rotation=dict(x=0, y=0, z=0)
    )
    assert not event.metadata[
        "lastActionSuccess"
    ], "position should not allow float input!"

    # orthographicSize expects float, not Vector3!
    error_message = None
    try:
        event = controller.step(
            action="AddThirdPartyCamera",
            position=dict(x=0, y=0, z=0),
            rotation=dict(x=0, y=0, z=0),
            orthographic=True,
            orthographicSize=dict(x=0, y=0, z=0),
        )
    except ValueError as e:
        error_message = str(e)

    assert error_message.startswith(
        "action: AddThirdPartyCamera has an invalid argument: orthographicSize"
    )


def test_update_third_party_camera(fifo_controller):
    # add a new camera
    expectedPosition = dict(x=1.2, y=2.3, z=3.4)
    expectedRotation = dict(x=30, y=40, z=50)
    expectedFieldOfView = 45.0
    e = fifo_controller.step(
        dict(
            action=Actions.AddThirdPartyCamera,
            position=expectedPosition,
            rotation=expectedRotation,
            fieldOfView=expectedFieldOfView,
        )
    )
    assert (
        len(fifo_controller.last_event.metadata[MultiAgentMetadata.thirdPartyCameras])
        == 1
    ), "there should be 1 camera"

    # update camera pose fully
    expectedPosition = dict(x=2.2, y=3.3, z=4.4)
    expectedRotation = dict(x=10, y=20, z=30)
    expectedInitialFieldOfView = 45.0
    e = fifo_controller.step(
        dict(
            action=Actions.UpdateThirdPartyCamera,
            thirdPartyCameraId=0,
            position=expectedPosition,
            rotation=expectedRotation,
        )
    )
    camera = e.metadata[MultiAgentMetadata.thirdPartyCameras][0]
    assert_near(
        camera[ThirdPartyCameraMetadata.position],
        expectedPosition,
        "position should have been updated",
    )
    assert_near(
        camera[ThirdPartyCameraMetadata.rotation],
        expectedRotation,
        "rotation should have been updated",
    )
    assert (
        camera[ThirdPartyCameraMetadata.fieldOfView] == expectedInitialFieldOfView
    ), "fieldOfView should not have changed"

    # partially update the camera pose
    changeFOV = 55.0
    expectedPosition2 = dict(x=3.2, z=5)
    expectedRotation2 = dict(y=90)
    e = fifo_controller.step(
        action=Actions.UpdateThirdPartyCamera,
        thirdPartyCameraId=0,
        fieldOfView=changeFOV,
        position=expectedPosition2,
        rotation=expectedRotation2,
    )
    camera = e.metadata[MultiAgentMetadata.thirdPartyCameras][0]
    assert (
        camera[ThirdPartyCameraMetadata.fieldOfView] == changeFOV
    ), "fieldOfView should have been updated"

    expectedPosition.update(expectedPosition2)
    expectedRotation.update(expectedRotation2)
    assert_near(
        camera[ThirdPartyCameraMetadata.position],
        expectedPosition,
        "position should been slightly updated",
    )
    assert_near(
        camera[ThirdPartyCameraMetadata.rotation],
        expectedRotation,
        "rotation should been slightly updated",
    )

    for fov in [-1, 181, 0]:
        e = fifo_controller.step(
            dict(
                action=Actions.UpdateThirdPartyCamera,
                thirdPartyCameraId=0,
                fieldOfView=fov,
            )
        )
        assert not e.metadata[
            "lastActionSuccess"
        ], "fieldOfView should fail outside of (0, 180)"
        assert_near(
            camera[ThirdPartyCameraMetadata.position],
            expectedPosition,
            "position should not have updated",
        )
        assert_near(
            camera[ThirdPartyCameraMetadata.rotation],
            expectedRotation,
            "rotation should not have updated",
        )


@pytest.mark.parametrize("controller", fifo_wsgi)
def test_rotate_look(controller):

    e = controller.step(dict(action="RotateLook", rotation=0, horizon=0))
    position = controller.last_event.metadata["agent"]["position"]
    rotation = controller.last_event.metadata["agent"]["rotation"]
    assert rotation == dict(x=0, y=0, z=0)
    e = controller.step(dict(action="RotateLook", rotation=90, horizon=31))
    assert e.metadata["agent"]["position"] == position
    assert int(e.metadata["agent"]["cameraHorizon"]) == 31
    assert e.metadata["agent"]["rotation"]["y"] == 90.0
    assert e.metadata["agent"]["rotation"]["x"] == 0.0
    assert e.metadata["agent"]["rotation"]["z"] == 0.0


@pytest.mark.parametrize("controller", fifo_wsgi)
def test_rotate_right(controller):

    e = controller.step(dict(action="RotateLook", rotation=0, horizon=0))
    position = controller.last_event.metadata["agent"]["position"]
    rotation = controller.last_event.metadata["agent"]["rotation"]
    assert rotation == dict(x=0, y=0, z=0)
    horizon = controller.last_event.metadata["agent"]["cameraHorizon"]
    e = controller.step(dict(action="RotateRight"))
    assert e.metadata["agent"]["position"] == position
    assert e.metadata["agent"]["cameraHorizon"] == horizon
    assert e.metadata["agent"]["rotation"]["y"] == 90.0
    assert e.metadata["agent"]["rotation"]["x"] == 0.0
    assert e.metadata["agent"]["rotation"]["z"] == 0.0


@pytest.mark.parametrize("controller", fifo_wsgi)
def test_open_aabb_cache(controller):
    objects = controller.last_event.metadata["objects"]
    obj = next(obj for obj in objects if obj["objectType"] == "Fridge")
    start_aabb = obj["axisAlignedBoundingBox"]

    open_event = controller.step(
        action="OpenObject",
        objectId=obj["objectId"],
        forceAction=True,
        raise_for_failure=True,
    )
    obj = next(
        obj for obj in open_event.metadata["objects"] if obj["objectType"] == "Fridge"
    )
    open_aabb = obj["axisAlignedBoundingBox"]
    assert start_aabb["size"] != open_aabb["size"]

    close_event = controller.step(
        action="CloseObject",
        objectId=obj["objectId"],
        forceAction=True,
        raise_for_failure=True,
    )
    obj = next(
        obj for obj in close_event.metadata["objects"] if obj["objectType"] == "Fridge"
    )
    close_aabb = obj["axisAlignedBoundingBox"]
    assert start_aabb["size"] == close_aabb["size"]

@pytest.mark.parametrize("controller", fifo_wsgi)
def test_toggle_stove(controller):
    position = {'x': -1.0, 'y': 0.9009982347488403, 'z': -2.25}
    action = position.copy()
    action["rotation"] = dict(y=90)
    action["horizon"] = 30.0
    action["standing"] = True
    action["action"] = "TeleportFull"
    event = controller.step(action, raise_for_failure=True)
    knob = next(
        obj
        for obj in controller.last_event.metadata["objects"]
        if obj["objectType"] == "StoveKnob" and obj['visible']
    )
    assert not knob['isToggled'], "knob should not be toggled"
    assert knob['visible']
    event = controller.step(dict(action='ToggleObjectOn', objectId=knob['objectId']), raise_for_failure=True)
    knob = event.get_object(knob['objectId'])
    assert knob['isToggled'], "knob should be toggled"

@pytest.mark.parametrize("controller", fifo_wsgi)
def test_open_interactable_with_filter(controller):
    position = {"x": -1.0, "y": 0.9009982347488403, "z": -0.5}
    action = position.copy()
    action["rotation"] = dict(y=90)
    action["horizon"] = 0
    action["standing"] = True
    action["action"] = "TeleportFull"
    controller.step(action, raise_for_failure=True)

    fridge = next(
        obj
        for obj in controller.last_event.metadata["objects"]
        if obj["objectType"] == "Fridge"
    )
    assert fridge["visible"], "Object is not interactable!"
    assert_near(controller.last_event.metadata["agent"]["position"], position)

    controller.step(dict(action="SetObjectFilter", objectIds=[]))
    assert controller.last_event.metadata["objects"] == []
    controller.step(
        action="OpenObject", objectId=fridge["objectId"], raise_for_failure=True,
    )

    controller.step(dict(action="ResetObjectFilter"))

    fridge = next(
        obj
        for obj in controller.last_event.metadata["objects"]
        if obj["objectType"] == "Fridge"
    )

    assert fridge["isOpen"]


@pytest.mark.parametrize("controller", fifo_wsgi)
def test_open_interactable(controller):
    position = {"x": -1.0, "y": 0.9009982347488403, "z": -0.5}
    action = position.copy()
    action["rotation"] = dict(y=90)
    action["horizon"] = 0
    action["standing"] = True
    action["action"] = "TeleportFull"
    controller.step(action, raise_for_failure=True)

    fridge = next(
        obj
        for obj in controller.last_event.metadata["objects"]
        if obj["objectType"] == "Fridge"
    )
    assert fridge["visible"], "Object is not interactable!"
    assert_near(controller.last_event.metadata["agent"]["position"], position)
    event = controller.step(
        action="OpenObject", objectId=fridge["objectId"], raise_for_failure=True,
    )
    fridge = next(
        obj
        for obj in controller.last_event.metadata["objects"]
        if obj["objectType"] == "Fridge"
    )
    assert fridge["isOpen"]


@pytest.mark.parametrize("controller", fifo_wsgi)
def test_open(controller):
    objects = controller.last_event.metadata["objects"]
    obj_to_open = next(obj for obj in objects if obj["objectType"] == "Fridge")

    # helper that returns obj_to_open from a new event
    def get_object(event, object_id):
        return next(
            obj for obj in event.metadata["objects"] if obj["objectId"] == object_id
        )

    for openness in [0.5, 0.7, 0]:
        event = controller.step(
            action="OpenObject",
            objectId=obj_to_open["objectId"],
            openness=openness,
            forceAction=True,
            raise_for_failure=True,
        )
        opened_obj = get_object(event, obj_to_open["objectId"])
        assert abs(opened_obj["openness"] - openness) < 1e-3, "Incorrect openness!"
        assert opened_obj["isOpen"] == (openness != 0), "isOpen incorrectly reported!"

    # test bad openness values
    for bad_openness in [-0.5, 1.5]:
        event = controller.step(
            action="OpenObject",
            objectId=obj_to_open["objectId"],
            openness=bad_openness,
            forceAction=True,
        )
        assert not event.metadata[
            "lastActionSuccess"
        ], "0.0 > Openness > 1.0 should fail!"

    # test backwards compatibility on moveMagnitude, where moveMagnitude
    # is now `openness`, but when moveMagnitude = 0 that corresponds to openness = 1.
    event = controller.step(
        action="OpenObject",
        objectId=obj_to_open["objectId"],
        forceAction=True,
        moveMagnitude=0,
    )
    opened_obj = get_object(event, obj_to_open["objectId"])
    assert (
        abs(opened_obj["openness"] - 1) < 1e-3
    ), "moveMagnitude=0 must have openness=1"
    assert opened_obj["isOpen"], "moveMagnitude isOpen incorrectly reported!"

    # another moveMagnitude check
    test_openness = 0.65
    event = controller.step(
        action="OpenObject",
        objectId=obj_to_open["objectId"],
        forceAction=True,
        moveMagnitude=test_openness,
    )
    opened_obj = get_object(event, obj_to_open["objectId"])
    assert (
        abs(opened_obj["openness"] - test_openness) < 1e-3
    ), "moveMagnitude is not working!"
    assert opened_obj["isOpen"], "moveMagnitude isOpen incorrectly reported!"

    # a CloseObject specific check
    event = controller.step(
        action="CloseObject", objectId=obj_to_open["objectId"], forceAction=True
    )
    obj = get_object(event, obj_to_open["objectId"])
    assert abs(obj["openness"] - 0) < 1e-3, "CloseObject openness should be 0"
    assert not obj["isOpen"], "CloseObject should report isOpen==false!"


def test_action_dispatch(fifo_controller):
    controller = fifo_controller
    event = controller.step(
        dict(action="TestActionDispatchFindAmbiguous"),
        typeName="UnityStandardAssets.Characters.FirstPerson.PhysicsRemoteFPSAgentController",
    )

    known_ambig = sorted(
        [
            "TestActionDispatchSAAmbig",
            "TestActionDispatchSAAmbig2",
            "ProcessControlCommand",
        ]
    )
    assert sorted(event.metadata["actionReturn"]) == known_ambig
    skip_reset(fifo_controller)


def test_action_dispatch_find_ambiguous_stochastic(fifo_controller):
    event = fifo_controller.step(
        dict(action="TestActionDispatchFindAmbiguous"),
        typeName="UnityStandardAssets.Characters.FirstPerson.StochasticRemoteFPSAgentController",
    )

    known_ambig = sorted(
        [
            "TestActionDispatchSAAmbig",
            "TestActionDispatchSAAmbig2",
            "ProcessControlCommand",
        ]
    )
    assert sorted(event.metadata["actionReturn"]) == known_ambig
    skip_reset(fifo_controller)


def test_action_dispatch_server_action_ambiguous2(fifo_controller):
    exception_thrown = False
    exception_message = None
    try:
        fifo_controller.step("TestActionDispatchSAAmbig2")
    except ValueError as e:
        exception_thrown = True
        exception_message = str(e)

    assert exception_thrown
    assert (
        "Ambiguous action: TestActionDispatchSAAmbig2 Signature match found in the same class"
        == exception_message
    )
    skip_reset(fifo_controller)


def test_action_dispatch_server_action_ambiguous(fifo_controller):
    exception_thrown = False
    exception_message = None
    try:
        fifo_controller.step("TestActionDispatchSAAmbig")
    except ValueError as e:
        exception_thrown = True
        exception_message = str(e)

    assert exception_thrown
    assert (
        exception_message
        == "Ambiguous action: TestActionDispatchSAAmbig Mixing a ServerAction method with overloaded methods is not permitted"
    )
    skip_reset(fifo_controller)


def test_action_dispatch_find_conflicts_stochastic(fifo_controller):
    event = fifo_controller.step(
        dict(action="TestActionDispatchFindConflicts"),
        typeName="UnityStandardAssets.Characters.FirstPerson.StochasticRemoteFPSAgentController",
    )
    known_conflicts = {
        "TestActionDispatchConflict": ["param22"],
    }
    assert event.metadata["actionReturn"] == known_conflicts
    skip_reset(fifo_controller)


def test_action_dispatch_find_conflicts_physics(fifo_controller):
    event = fifo_controller.step(
        dict(action="TestActionDispatchFindConflicts"),
        typeName="UnityStandardAssets.Characters.FirstPerson.PhysicsRemoteFPSAgentController",
    )
    known_conflicts = {
        "TestActionDispatchConflict": ["param22"],
    }

    assert event.metadata["actionReturn"] == known_conflicts

    skip_reset(fifo_controller)


def test_action_dispatch_missing_args(fifo_controller):
    caught_exception = False
    try:
        event = fifo_controller.step(
            dict(action="TestActionDispatchNoop", param6="foo")
        )
        print(event.metadata["actionReturn"])
    except ValueError as e:
        caught_exception = True
    assert caught_exception
    assert fifo_controller.last_event.metadata["errorCode"] == "MissingArguments"
    skip_reset(fifo_controller)


def test_action_dispatch_invalid_action(fifo_controller):
    caught_exception = False
    try:
        event = fifo_controller.step(dict(action="TestActionDispatchNoopFoo"))
    except ValueError as e:
        caught_exception = True
    assert caught_exception
    assert fifo_controller.last_event.metadata["errorCode"] == "InvalidAction"
    skip_reset(fifo_controller)


def test_action_dispatch_empty(fifo_controller):
    event = fifo_controller.step(dict(action="TestActionDispatchNoop"))
    assert event.metadata["actionReturn"] == "emptyargs"
    skip_reset(fifo_controller)


def test_action_disptatch_one_param(fifo_controller):
    event = fifo_controller.step(dict(action="TestActionDispatchNoop", param1=True))
    assert event.metadata["actionReturn"] == "param1"
    skip_reset(fifo_controller)


def test_action_disptatch_two_param(fifo_controller):
    event = fifo_controller.step(
        dict(action="TestActionDispatchNoop", param1=True, param2=False)
    )
    assert event.metadata["actionReturn"] == "param1 param2"
    skip_reset(fifo_controller)


def test_action_disptatch_two_param_with_default(fifo_controller):
    event = fifo_controller.step(
        dict(action="TestActionDispatchNoop2", param3=True, param4="foobar")
    )
    assert event.metadata["actionReturn"] == "param3 param4/default foobar"
    skip_reset(fifo_controller)


def test_action_disptatch_two_param_with_default_empty(fifo_controller):
    event = fifo_controller.step(dict(action="TestActionDispatchNoop2", param3=True))
    assert event.metadata["actionReturn"] == "param3 param4/default foo"
    skip_reset(fifo_controller)


def test_action_disptatch_serveraction_default(fifo_controller):
    event = fifo_controller.step(dict(action="TestActionDispatchNoopServerAction"))
    assert event.metadata["actionReturn"] == "serveraction"
    skip_reset(fifo_controller)


def test_action_disptatch_serveraction_with_object_id(fifo_controller):
    event = fifo_controller.step(
        dict(action="TestActionDispatchNoopServerAction", objectId="candle|1|2|3")
    )
    assert event.metadata["actionReturn"] == "serveraction"
    skip_reset(fifo_controller)


def test_action_disptatch_all_default(fifo_controller):
    event = fifo_controller.step(dict(action="TestActionDispatchNoopAllDefault"))
    assert event.metadata["actionReturn"] == "alldefault"
    skip_reset(fifo_controller)


def test_action_disptatch_some_default(fifo_controller):
    event = fifo_controller.step(
        dict(action="TestActionDispatchNoopAllDefault2", param12=9.0)
    )
    assert event.metadata["actionReturn"] == "somedefault"
    skip_reset(fifo_controller)


@pytest.mark.parametrize("controller", fifo_wsgi)
def test_moveahead(controller):
    teleport_to_base_location(controller)
    controller.step(dict(action="MoveAhead"), raise_for_failure=True)
    position = controller.last_event.metadata["agent"]["position"]
    assert_near(position, dict(x=-1.5, z=-1.25, y=0.901))


@pytest.mark.parametrize("controller", fifo_wsgi)
def test_moveback(controller):
    teleport_to_base_location(controller)
    controller.step(dict(action="MoveBack"), raise_for_failure=True)
    position = controller.last_event.metadata["agent"]["position"]
    assert_near(position, dict(x=-1.5, z=-1.75, y=0.900998652))


@pytest.mark.parametrize("controller", fifo_wsgi)
def test_moveleft(controller):
    teleport_to_base_location(controller)
    controller.step(dict(action="MoveLeft"), raise_for_failure=True)
    position = controller.last_event.metadata["agent"]["position"]
    assert_near(position, dict(x=-1.75, z=-1.5, y=0.901))


@pytest.mark.parametrize("controller", fifo_wsgi)
def test_moveright(controller):
    teleport_to_base_location(controller)
    controller.step(dict(action="MoveRight"), raise_for_failure=True)
    position = controller.last_event.metadata["agent"]["position"]
    assert_near(position, dict(x=-1.25, z=-1.5, y=0.901))


@pytest.mark.parametrize("controller", fifo_wsgi)
def test_moveahead_mag(controller):
    teleport_to_base_location(controller)
    controller.step(dict(action="MoveAhead", moveMagnitude=0.5), raise_for_failure=True)
    position = controller.last_event.metadata["agent"]["position"]
    assert_near(position, dict(x=-1.5, z=-1, y=0.9009983))


@pytest.mark.parametrize("controller", fifo_wsgi)
def test_moveahead_fail(controller):
    teleport_to_base_location(controller)
    controller.step(dict(action="MoveAhead", moveMagnitude=5.0))
    assert not controller.last_event.metadata["lastActionSuccess"]


@pytest.mark.parametrize("controller", fifo_wsgi)
def test_jsonschema_metadata(controller):
    event = controller.step(dict(action="Pass"))
    with open(os.path.join(TESTS_DATA_DIR, "metadata-schema.json")) as f:
        schema = json.loads(f.read())

    jsonschema.validate(instance=event.metadata, schema=schema)
    skip_reset(controller)


@pytest.mark.parametrize("controller", fifo_wsgi)
def test_arm_jsonschema_metadata(controller):
    controller.reset(agentMode="arm")
    event = controller.step(action="Pass")
    with open(os.path.join(TESTS_DATA_DIR, "arm-metadata-schema.json")) as f:
        schema = json.loads(f.read())

    jsonschema.validate(instance=event.metadata, schema=schema)


@pytest.mark.parametrize("controller", fifo_wsgi)
def test_get_scenes_in_build(controller):
    scenes = set()
    for g in glob.glob("unity/Assets/Scenes/*.unity"):
        scenes.add(os.path.splitext(os.path.basename(g))[0])

    event = controller.step(dict(action="GetScenesInBuild"), raise_for_failure=True)
    return_scenes = set(event.metadata["actionReturn"])

    # not testing for private scenes
    diff = scenes - return_scenes
    assert len(diff) == 0, "scenes in build diff: %s" % diff
    skip_reset(controller)


@pytest.mark.parametrize("controller", fifo_wsgi)
def test_get_reachable_positions(controller):
    event = controller.step("GetReachablePositions")
    assert (
        event.metadata["actionReturn"] == event.metadata["reachablePositions"]
    ), "reachablePositions should map to actionReturn!"
    assert len(event.metadata["reachablePositions"]) > 0 and isinstance(
        event.metadata["reachablePositions"], list
    ), "reachablePositions/actionReturn should not be empty after calling GetReachablePositions!"

    assert "reachablePositions" not in event.metadata.keys()
    event = controller.step("Pass")
    try:
        event.metadata["reachablePositions"]
        assert (
            False
        ), "reachablePositions shouldn't be available without calling action='GetReachablePositions'."
    except:
        pass

def test_per_step_instance_segmentation(fifo_controller):
    fifo_controller.reset(
        TEST_SCENE,
        width=300,
        height=300,
        renderInstanceSegmentation=False
    )
    event = fifo_controller.step("RotateRight")
    assert event.instance_segmentation_frame is None
    event = fifo_controller.step("Pass", renderInstanceSegmentation=True)
    assert event.instance_segmentation_frame is not None

#  Test for Issue: 477
def test_change_resolution_image_synthesis(fifo_controller):
    fifo_controller.reset(
        TEST_SCENE,
        width=300,
        height=300,
        renderInstanceSegmentation=True,
        renderDepthImage=True,
        renderSemanticSegmentation=True,
    )
    fifo_controller.step("RotateRight")
    first_event = fifo_controller.last_event
    first_depth_frame = fifo_controller.last_event.depth_frame
    first_instance_frame = fifo_controller.last_event.instance_segmentation_frame
    first_sem_frame = fifo_controller.last_event.semantic_segmentation_frame
    event = fifo_controller.step(action="ChangeResolution", x=500, y=500)
    assert event.depth_frame.shape == (500, 500)
    assert event.instance_segmentation_frame.shape == (500, 500, 3)
    assert event.semantic_segmentation_frame.shape == (500, 500, 3)
    event = fifo_controller.step(action="ChangeResolution", x=300, y=300)
    assert event.depth_frame.shape == (300, 300)
    assert event.instance_segmentation_frame.shape == (300, 300, 3)
    assert event.semantic_segmentation_frame.shape == (300, 300, 3)
    assert np.allclose(event.depth_frame, first_depth_frame, atol=0.001)
    assert np.array_equal(event.instance_segmentation_frame, first_instance_frame)
    assert np.array_equal(event.semantic_segmentation_frame, first_sem_frame)
    assert first_event.color_to_object_id == event.color_to_object_id
    assert first_event.object_id_to_color == event.object_id_to_color


@pytest.mark.parametrize("controller", fifo_wsgi)
def test_change_resolution(controller):
    event = controller.step(dict(action="Pass"), raise_for_failure=True)
    assert event.frame.shape == (300, 300, 3)
    event = controller.step(
        dict(action="ChangeResolution", x=400, y=400), raise_for_failure=True
    )
    assert event.frame.shape == (400, 400, 3)
    assert event.screen_width == 400
    assert event.screen_height == 400
    event = controller.step(
        dict(action="ChangeResolution", x=300, y=300), raise_for_failure=True
    )


@pytest.mark.parametrize("controller", fifo_wsgi)
def test_teleport(controller):
    # Checking y coordinate adjustment works
    controller.step(
        "TeleportFull", **{**BASE_FP28_LOCATION, "y": 0.95}, raise_for_failure=True
    )
    position = controller.last_event.metadata["agent"]["position"]
    assert_near(position, BASE_FP28_POSITION)

    controller.step(
        "TeleportFull",
        **{**BASE_FP28_LOCATION, "x": -2.0, "z": -2.5, "y": 0.95},
        raise_for_failure=True,
    )
    position = controller.last_event.metadata["agent"]["position"]
    assert_near(position, dict(x=-2.0, z=-2.5, y=0.901))

    # Teleporting too high
    before_position = controller.last_event.metadata["agent"]["position"]
    controller.step(
        "Teleport", **{**BASE_FP28_LOCATION, "y": 1.0},
    )
    assert not controller.last_event.metadata[
        "lastActionSuccess"
    ], "Teleport should not allow changes for more than 0.05 in the y coordinate."
    assert (
        controller.last_event.metadata["agent"]["position"] == before_position
    ), "After failed teleport, the agent's position should not change."

    # Teleporting into an object
    controller.step(
        "Teleport", **{**BASE_FP28_LOCATION, "z": -3.5},
    )
    assert not controller.last_event.metadata[
        "lastActionSuccess"
    ], "Should not be able to teleport into an object."

    # Teleporting into a wall
    controller.step(
        "Teleport", **{**BASE_FP28_LOCATION, "z": 0},
    )
    assert not controller.last_event.metadata[
        "lastActionSuccess"
    ], "Should not be able to teleport into a wall."

    # DEFAULT AGENT TEST
    # make sure Teleport works with default args
    a1 = controller.last_event.metadata["agent"]
    a2 = controller.step("Teleport", horizon=10).metadata["agent"]
    assert abs(a2["cameraHorizon"] - 10) < 1e-2, "cameraHorizon should be ~10!"

    # all should be the same except for horizon
    assert_near(a1["position"], a2["position"])
    assert_near(a1["rotation"], a2["rotation"])
    assert (
        a1["isStanding"] == a2["isStanding"]
    ), "Agent should remain in same standing when unspecified!"
    assert a1["isStanding"] != None, "Agent isStanding should be set for physics agent!"

    # make sure float rotation works
    # TODO: readd this when it actually works
    # agent = controller.step('TeleportFull', rotation=25).metadata['agent']
    # assert_near(agent['rotation']['y'], 25)

    # test out of bounds with default agent
    for action in ["Teleport", "TeleportFull"]:
        try:
            controller.step(
                action="TeleportFull",
                position=dict(x=2000, y=0, z=9000),
                rotation=dict(x=0, y=90, z=0),
                horizon=30,
                raise_for_failure=True,
            )
            assert False, "Out of bounds teleport not caught by physics agent"
        except:
            pass

    # Teleporting with the locobot and drone, which don't support standing
    for agent in ["locobot", "drone"]:
        event = controller.reset(agentMode=agent)
        assert event.metadata["agent"]["isStanding"] is None, agent + " cannot stand!"

        # Only degrees of freedom on the locobot
        for action in ["Teleport", "TeleportFull"]:
            event = controller.step(
                action=action,
                position=dict(x=-1.5, y=0.9, z=-1.5),
                rotation=dict(x=0, y=90, z=0),
                horizon=30,
            )
            assert event.metadata["lastActionSuccess"], (
                agent + " must be able to TeleportFull without passing in standing!"
            )
            try:
                event = controller.step(
                    action=action,
                    position=dict(x=-1.5, y=0.9, z=-1.5),
                    rotation=dict(x=0, y=90, z=0),
                    horizon=30,
                    standing=True,
                )
                assert False, (
                    agent + " should not be able to pass in standing to teleport!"
                )
            except:
                pass

            # test out of bounds with default agent
            try:
                controller.step(
                    action=action,
                    position=dict(x=2000, y=0, z=9000),
                    rotation=dict(x=0, y=90, z=0),
                    horizon=30,
                    raise_for_failure=True,
                )
                assert False, "Out of bounds teleport not caught by physics agent"
            except:
                pass

        # make sure Teleport works with default args
        a1 = controller.last_event.metadata["agent"]
        a2 = controller.step("Teleport", horizon=10).metadata["agent"]
        assert abs(a2["cameraHorizon"] - 10) < 1e-2, "cameraHorizon should be ~10!"

        # all should be the same except for horizon
        assert_near(a1["position"], a2["position"])
        assert_near(a1["rotation"], a2["rotation"])

        # TODO: readd this when it actually works.
        # make sure float rotation works
        # if agent == "locobot":
        # agent = controller.step('TeleportFull', rotation=25).metadata['agent']
        # assert_near(agent['rotation']['y'], 25)

    controller.reset(agentMode="default")


@pytest.mark.parametrize("controller", fifo_wsgi)
def test_get_interactable_poses(controller):
    fridgeId = next(
        obj["objectId"]
        for obj in controller.last_event.metadata["objects"]
        if obj["objectType"] == "Fridge"
    )
    event = controller.step("GetInteractablePoses", objectId=fridgeId)
    poses = event.metadata["actionReturn"]
    assert (
        600 > len(poses) > 400
    ), "Should have around 400 interactable poses next to the fridge!"

    # teleport to a random pose
    pose = poses[len(poses) // 2]
    event = controller.step("TeleportFull", **pose)

    # assumes 1 fridge in the scene
    fridge = next(
        obj
        for obj in controller.last_event.metadata["objects"]
        if obj["objectType"] == "Fridge"
    )
    assert fridge["visible"], "Object is not interactable!"

    # tests that teleport correctly works with **syntax
    assert (
        abs(pose["x"] - event.metadata["agent"]["position"]["x"]) < 1e-3
    ), "Agent x position off!"
    assert (
        abs(pose["z"] - event.metadata["agent"]["position"]["z"]) < 1e-3
    ), "Agent z position off!"
    assert (
        abs(pose["rotation"] - event.metadata["agent"]["rotation"]["y"]) < 1e-3
    ), "Agent rotation off!"
    assert (
        abs(pose["horizon"] - event.metadata["agent"]["cameraHorizon"]) < 1e-3
    ), "Agent horizon off!"
    assert (
        pose["standing"] == event.metadata["agent"]["isStanding"]
    ), "Agent's isStanding is off!"

    # potato should be inside of the fridge (and, thus, non interactable)
    potatoId = next(
        obj["objectId"]
        for obj in controller.last_event.metadata["objects"]
        if obj["objectType"] == "Potato"
    )
    event = controller.step("GetInteractablePoses", objectId=potatoId)
    assert (
        len(event.metadata["actionReturn"]) == 0
    ), "Potato is inside of fridge, and thus, shouldn't be interactable"
    assert event.metadata[
        "lastActionSuccess"
    ], "GetInteractablePoses with Potato shouldn't have failed!"

    # assertion for maxPoses
    event = controller.step("GetInteractablePoses", objectId=fridgeId, maxPoses=50)
    assert len(event.metadata["actionReturn"]) == 50, "maxPoses should be capped at 50!"

    # assert only checking certain horizons and rotations is working correctly
    horizons = [0, 30]
    rotations = [0, 45]
    event = controller.step(
        "GetInteractablePoses",
        objectId=fridgeId,
        horizons=horizons,
        rotations=rotations,
    )
    for pose in event.metadata["actionReturn"]:
        horizon_works = False
        for horizon in horizons:
            if abs(pose["horizon"] - horizon) < 1e-3:
                horizon_works = True
                break
        assert horizon_works, "Not expecting horizon: " + pose["horizon"]

        rotation_works = False
        for rotation in rotations:
            if abs(pose["rotation"] - rotation) < 1e-3:
                rotation_works = True
                break
        assert rotation_works, "Not expecting rotation: " + pose["rotation"]

    # assert only checking certain horizons and rotations is working correctly
    event = controller.step("GetInteractablePoses", objectId=fridgeId, rotations=[270])
    assert (
        len(event.metadata["actionReturn"]) == 0
    ), "Fridge shouldn't be viewable from this rotation!"
    assert event.metadata[
        "lastActionSuccess"
    ], "GetInteractablePoses with Fridge shouldn't have failed!"

    # test maxDistance
    event = controller.step("GetInteractablePoses", objectId=fridgeId, maxDistance=5)
    assert (
        1300 > len(event.metadata["actionReturn"]) > 1100
    ), "GetInteractablePoses with large maxDistance is off!"


@pytest.mark.parametrize("controller", fifo_wsgi)
def test_2d_semantic_hulls(controller):
    from shapely.geometry import Polygon

    controller.reset(TEST_SCENE)
    obj_name_to_obj_id = {
        o["name"]: o["objectId"] for o in controller.last_event.metadata["objects"]
    }
    # Used to save fixed object locations.
    # with open("ai2thor/tests/data/floorplan28-fixed-obj-poses.json", "w") as f:
    #     json.dump(
    #         [
    #             {k: o[k] for k in ["name", "position", "rotation"]}
    #             for o in controller.last_event.metadata["objects"]
    #         ],
    #         f
    #     )
    with open("ai2thor/tests/data/floorplan28-fixed-obj-poses.json", "r") as f:
        fixed_obj_poses = json.load(f)
        for o in fixed_obj_poses:
            teleport_success = controller.step(
                "TeleportObject",
                objectId=obj_name_to_obj_id[o["name"]],
                position=o["position"],
                rotation=o["rotation"],
                forceAction=True,
                forceKinematic=True,
                makeUnbreakable=True,
            ).metadata["lastActionSuccess"]
            assert teleport_success

    object_types = ["Tomato", "Drawer", "Fridge"]
    object_ids = [
        "Mug|-03.15|+00.82|-03.47",
        "Faucet|-00.39|+00.93|-03.61",
        "StoveBurner|-00.22|+00.92|-01.85",
    ]

    def get_rounded_hulls(**kwargs):
        if "objectId" in kwargs:
            md = controller.step("Get2DSemanticHull", **kwargs).metadata
        else:
            md = controller.step("Get2DSemanticHulls", **kwargs).metadata
        assert md["lastActionSuccess"] and md["errorMessage"] == ""
        hulls = md["actionReturn"]
        if isinstance(hulls, list):
            return np.array(hulls, dtype=float).round(4).tolist()
        else:
            return {
                k: np.array(v, dtype=float).round(4).tolist()
                for k, v in md["actionReturn"].items()
            }

    # All objects
    hulls_all = get_rounded_hulls()

    # Filtering by object types
    hulls_type_filtered = get_rounded_hulls(objectTypes=object_types)

    # Filtering by object ids
    hulls_id_filtered = get_rounded_hulls(objectIds=object_ids)

    # Single object id
    hulls_single_object = get_rounded_hulls(objectId=object_ids[0])

    # Used to save the ground truth values:
    # objects = controller.last_event.metadata["objects"]
    # objects_poses = [
    #     {"objectName": o["name"], "position": o["position"], "rotation": o["rotation"]} for o in objects
    # ]
    # print(controller.step("SetObjectPoses", objectPoses=objects_poses).metadata)
    # with open("ai2thor/tests/data/semantic-2d-hulls.json", "w") as f:
    #     json.dump(
    #         {
    #             "all": hulls_all,
    #             "type_filtered": hulls_type_filtered,
    #             "id_filtered": hulls_id_filtered,
    #             "single_object": hulls_single_object,
    #         },
    #         f
    #     )

    with open("ai2thor/tests/data/semantic-2d-hulls.json") as f:
        truth = json.load(f)

    def assert_almost_equal(a, b):
        if isinstance(a, list):
            pa = Polygon(a)
            pb = Polygon(b)
            pa_area = pa.area
            pb_area = pb.area
            sym_diff_area = pa.symmetric_difference(pb).area
            # TODO: There seems to be a difference in the geometry reported by Unity when in
            #   Linux vs Mac. I've had to increase the below check to the relatively generous <0.02
            #   to get this test to pass.
            assert sym_diff_area / max([1e-6, pa_area, pb_area]) < 2e-2, (
                f"Polygons have to large an area ({sym_diff_area}) in their symmetric difference"
                f" compared to their sizes ({pa_area}, {pb_area}). Hulls:\n"
                f"{json.dumps(a)}\n"
                f"{json.dumps(b)}\n"
            )
        else:
            for k in set(a.keys()) | set(b.keys()):
                try:
                    assert_almost_equal(a[k], b[k])
                except AssertionError as e:
                    raise AssertionError(f"For {k}: {e.args[0]}")

    assert_almost_equal(truth["all"], hulls_all)
    assert_almost_equal(truth["type_filtered"], hulls_type_filtered)
    assert_almost_equal(truth["id_filtered"], hulls_id_filtered)
    assert_almost_equal(truth["single_object"], hulls_single_object)

    # Should fail when given types and ids
    assert not controller.step(
        "Get2DSemanticHulls", objectTypes=object_types, objectIds=object_ids
    ).metadata["lastActionSuccess"]


@pytest.mark.parametrize("controller", fifo_wsgi)
@pytest.mark.skip(reason="Colliders need to be moved closer to objects.")
def test_get_object_in_frame(controller):
    controller.reset(scene=TEST_SCENE, agentMode="default")
    event = controller.step(
        action="TeleportFull",
        position=dict(x=-1, y=0.900998235, z=-1.25),
        rotation=dict(x=0, y=90, z=0),
        horizon=0,
        standing=True,
    )
    assert event, "TeleportFull should have succeeded!"

    query = controller.step("GetObjectInFrame", x=0.6, y=0.6)
    assert not query, "x=0.6, y=0.6 should fail!"

    query = controller.step("GetObjectInFrame", x=0.6, y=0.4)
    assert query.metadata["actionReturn"].startswith(
        "Cabinet"
    ), "x=0.6, y=0.4 should have a cabinet!"

    query = controller.step("GetObjectInFrame", x=0.3, y=0.5)
    assert query.metadata["actionReturn"].startswith(
        "Fridge"
    ), "x=0.3, y=0.5 should have a fridge!"

    event = controller.reset(renderInstanceSegmentation=True)
    assert event.metadata["screenHeight"] == 300
    assert event.metadata["screenWidth"] == 300

    # exhaustive test
    num_tested = 0
    for objectId in event.instance_masks.keys():
        for obj in event.metadata["objects"]:
            if obj["objectId"] == objectId:
                break
        else:
            # object may not be a sim object (e.g., ceiling, floor, wall, etc.)
            continue

        num_tested += 1

        mask = event.instance_masks[objectId]

        # subtract 3 pixels off the edge due to pixels being rounded and collider issues
        mask = Image.fromarray(mask)
        for _ in range(3):
            mask_edges = mask.filter(ImageFilter.FIND_EDGES)
            mask = ImageChops.subtract(mask, mask_edges)
        mask = np.array(mask)

        ys, xs = mask.nonzero()
        for x, y in zip(xs, ys):
            event = controller.step(
                action="GetObjectInFrame", x=x / 300, y=y / 300, forceAction=True
            )
            assert (
                event.metadata["actionReturn"] == objectId
            ), f"Failed at ({x / 300}, {y / 300}) for {objectId} with agent at: {event.metadata['agent']}"

    assert (
        num_tested == 29
    ), "There should be 29 objects in the frame, based on the agent's pose!"


@pytest.mark.parametrize("controller", fifo_wsgi)
def test_get_coordinate_from_raycast(controller):
    controller.reset(scene=TEST_SCENE)
    event = controller.step(
        action="TeleportFull",
        position=dict(x=-1.5, y=0.900998235, z=-1.5),
        rotation=dict(x=0, y=90, z=0),
        horizon=0,
        standing=True,
    )
    assert event, "TeleportFull should have succeeded!"

    for x, y in [(1.5, 0.5), (1.1, 0.3), (-0.1, 0.8), (-0.5, -0.3)]:
        query = controller.step("GetCoordinateFromRaycast", x=x, y=y)
        assert not query, f"x={x}, y={y} should fail!"

    query = controller.step("GetCoordinateFromRaycast", x=0.5, y=0.5)
    assert_near(
        query.metadata["actionReturn"],
        {"x": -0.344259053, "y": 1.57599819, "z": -1.49999917},
    )

    query = controller.step("GetCoordinateFromRaycast", x=0.5, y=0.2)
    assert_near(
        query.metadata["actionReturn"],
        {"x": -0.344259053, "y": 2.2694428, "z": -1.49999917},
    )

    query = controller.step("GetCoordinateFromRaycast", x=0.25, y=0.5)
    assert_near(
        query.metadata["actionReturn"],
        {"x": -0.5968407392501831, "y": 1.5759981870651245, "z": -1.0484200716018677},
    )


@pytest.mark.parametrize("controller", fifo_wsgi)
def test_get_reachable_positions_with_directions_relative_agent(controller):
    controller.reset(TEST_SCENE)

    event = controller.step("GetReachablePositions")
    num_reachable_aligned = len(event.metadata["actionReturn"])
    assert 100 < num_reachable_aligned < 125

    controller.step(
        action="TeleportFull",
        position=dict(x=-1, y=0.900998235, z=-1.25),
        rotation=dict(x=0, y=49.11111, z=0),
        horizon=0,
        standing=True,
    )
    event = controller.step("GetReachablePositions")
    num_reachable_aligned_after_teleport = len(event.metadata["actionReturn"])
    assert num_reachable_aligned == num_reachable_aligned_after_teleport

    event = controller.step("GetReachablePositions", directionsRelativeAgent=True)
    num_reachable_unaligned = len(event.metadata["actionReturn"])
    assert 100 < num_reachable_unaligned < 125

    assert (
        num_reachable_unaligned != num_reachable_aligned
    ), "Number of reachable positions should differ when using `directionsRelativeAgent`"


@pytest.mark.parametrize("controller", fifo_wsgi)
def test_manipulathor_move(controller):
    event = controller.reset(scene=TEST_SCENE, agentMode="arm")
    assert_near(
        point1={"x": -1.5, "y": 0.9009982347488403, "z": -1.5},
        point2=event.metadata["agent"]["position"],
    )

    event = controller.step(action="MoveAgent", ahead=0.25, right=0.15)
    assert_near(
        point1={"x": -1.649999976158142, "y": 0.9009982347488403, "z": -1.75},
        point2=event.metadata["agent"]["position"],
    )


@pytest.mark.parametrize("controller", fifo_wsgi)
def test_manipulathor_rotate(controller):
    event = controller.reset(scene=TEST_SCENE, agentMode="arm")
    assert_near(
        point1={"x": -0.0, "y": 180.0, "z": 0.0},
        point2=event.metadata["agent"]["rotation"],
    )

    event = controller.step(action="RotateAgent", degrees=60)
    assert_near(
        point1={"x": -0.0, "y": 240.0, "z": 0.0},
        point2=event.metadata["agent"]["rotation"],
    )


@pytest.mark.parametrize("controller", fifo_wsgi)
def test_unsupported_manipulathor(controller):
    controller.reset(agentMode="arm")
    unsupported_actions = [
        "MoveAhead",
        "MoveBack",
        "MoveLeft",
        "MoveRight",
        "RotateRight",
        "RotateLeft",
    ]

    for action in unsupported_actions:
        event = controller.step(action)
        assert not event, action + " should have failed with agentMode=arm"

    event = controller.step(action="PickupObject", x=0.5, y=0.5)
    assert not event, "PickupObject(x, y) should have failed with agentMode=arm"

    objectId = next(
        obj["objectId"] for obj in event.metadata["objects"] if obj["pickupable"]
    )
    event = controller.step(action="PickupObject", objectId=objectId, forceAction=True)
    assert not event, "PickupObject(objectId) should have failed with agentMode=arm"


@pytest.mark.parametrize("controller", fifo_wsgi)
def test_invalid_arguments(controller):
    controller.reset()
    with pytest.raises(ValueError):
        event = controller.step(
            action="PutObject",
            x=0.0,
            y=0.0,
            z=1.0,
            forceAction=False,
            placeStationary=True,
        )
    print("Err {0}".format(controller.last_event.metadata["lastActionSuccess"]))
    assert not controller.last_event.metadata[
        "lastActionSuccess"
    ], "Extra parameter 'z' in action"
    assert controller.last_event.metadata[
        "errorMessage"
    ], "errorMessage with invalid argument"


@pytest.mark.parametrize("controller", fifo_wsgi)
def test_segmentation_colors(controller):
    event = controller.reset(renderSemanticSegmentation=True)
    fridge_color = event.object_id_to_color["Fridge"]
    assert (
        event.color_to_object_id[fridge_color] == "Fridge"
    ), "Fridge should have this color semantic seg"

    event = controller.reset(
        renderSemanticSegmentation=False, renderInstanceSegmentation=True
    )
    fridge_color = event.object_id_to_color["Fridge"]
    assert (
        event.color_to_object_id[fridge_color] == "Fridge"
    ), "Fridge should have this color on instance seg"

