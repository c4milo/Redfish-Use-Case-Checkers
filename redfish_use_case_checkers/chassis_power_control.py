# Copyright Notice:
# Copyright 2017-2026 Distributed Management Task Force, Inc. All rights reserved.
# License: BSD 3-Clause License. For full text see link: https://github.com/DMTF/Redfish-Use-Case-Checkers/blob/main/LICENSE.md

"""
Chassis Power Control Use Cases

File : chassis_power_control.py

Brief : This file contains the definitions and functionalities for testing
        use cases for chassis power control
"""

import redfish_utilities
import time

from redfish_use_case_checkers.system_under_test import SystemUnderTest
from redfish_use_case_checkers import logger

CAT_NAME = "Chassis Power Control"
TEST_CHASSIS_COUNT = (
    "Resettable Chassis Count",
    "Verifies the chassis list is not empty and locates chassis that support the Reset action",
    "Locates the ChassisCollection resource and performs GET on all members.",
)
TEST_RESET_TYPE = (
    "Chassis Reset Type",
    "Verifies each resettable chassis reports supported reset types",
    "Inspects the Reset action for each chassis for the supported reset types.",
)
TEST_RESET_OPERATION = (
    "Chassis Reset Operation",
    "Verifies that a chassis can be reset and reports schema-defined health states throughout",
    "Performs a POST operation on the Reset action on the Chassis resource.  Monitors 'PowerState' on the Chassis resource until it reaches the expected value, and verifies each sampled 'Status.State' is a value the Resource schema defines.",
)
TEST_LIST = [TEST_CHASSIS_COUNT, TEST_RESET_TYPE, TEST_RESET_OPERATION]

# The 'ResetType' values defined by the DMTF Resource schema, as of v1.24.0.
# An advertised allowable value outside this set is not Redfish vocabulary,
# and a generic client cannot know what to send.
RESET_TYPE_VALUES = frozenset(
    [
        "On",
        "ForceOff",
        "GracefulShutdown",
        "GracefulRestart",
        "ForceRestart",
        "Nmi",
        "ForceOn",
        "PushPowerButton",
        "PowerCycle",
        "Suspend",
        "Pause",
        "Resume",
        "FullPowerCycle",
        "Sleep",
        "Hibernate",
    ]
)

# The reset types whose expected end state is powered off; every other
# schema-defined type ends powered on
OFF_RESET_TYPES = frozenset(["ForceOff", "GracefulShutdown", "Suspend", "Hibernate"])

# The 'State' values defined by the 'Status' object in the DMTF Resource
# schema, as of v1.24.0; the newest value, 'Degraded', was added in v1.19.0.
# A value outside this set, such as 'Standby', is not Redfish vocabulary and
# clients cannot act on it.
RESOURCE_STATE_VALUES = frozenset(
    [
        "Enabled",
        "Disabled",
        "StandbyOffline",
        "StandbySpare",
        "InTest",
        "Starting",
        "Absent",
        "UnavailableOffline",
        "Deferring",
        "Quiesced",
        "Updating",
        "Degraded",
        "Qualified",
    ]
)


def use_cases(sut: SystemUnderTest):
    """
    Performs the use cases for chassis power control

    Args:
        sut: The system under test
    """

    logger.log_use_case_category_header(CAT_NAME)

    # Set initial results
    sut.add_results_category(CAT_NAME, TEST_LIST)

    # Check that there is a chassis collection
    if "Chassis" not in sut.service_root:
        for test in TEST_LIST:
            sut.add_test_result(CAT_NAME, test[0], "", "SKIP", "Service does not contain a chassis collection.")
        logger.log_use_case_category_footer(CAT_NAME)
        return

    # Go through the test cases
    test_chassis = chassis_power_test_count(sut)
    reset_capabilities = chassis_power_test_reset_type(sut, test_chassis)
    chassis_power_test_reset_operation(sut, test_chassis, reset_capabilities)

    logger.log_use_case_category_footer(CAT_NAME)


def chassis_power_test_count(sut: SystemUnderTest):
    """
    Performs the resettable chassis count test

    Args:
        sut: The system under test

    Returns:
        An array of chassis found that support the Reset action
    """

    test_name = TEST_CHASSIS_COUNT[0]
    logger.log_use_case_test_header(CAT_NAME, test_name)
    chassis = []
    chassis_members = []

    # Get the list of chassis
    operation = "Counting the members of the chassis collection"
    logger.logger.info(operation)
    try:
        collection_uri = sut.service_root["Chassis"]["@odata.id"]
        collection = sut.session.get(collection_uri)
        redfish_utilities.verify_response(collection)
        chassis_members = [member["@odata.id"] for member in collection.dict.get("Members", [])]
        if len(chassis_members) == 0:
            sut.add_test_result(CAT_NAME, test_name, operation, "FAIL", "No chassis were found.")
        else:
            sut.add_test_result(CAT_NAME, test_name, operation, "PASS")
    except Exception as err:
        sut.add_test_result(CAT_NAME, test_name, operation, "FAIL", "Failed to get the chassis list ({}).".format(err))

    # Get each member of the chassis collection; only those advertising the
    # Reset action move on to the remaining tests
    for member in chassis_members:
        operation = "Getting chassis '{}'".format(member)
        logger.logger.info(operation)
        try:
            member_resp = sut.session.get(member)
            redfish_utilities.verify_response(member_resp)
            if "#Chassis.Reset" in member_resp.dict.get("Actions", {}):
                chassis.append(member_resp.dict)
                sut.add_test_result(CAT_NAME, test_name, operation, "PASS")
            else:
                sut.add_test_result(
                    CAT_NAME,
                    test_name,
                    operation,
                    "SKIP",
                    "Chassis '{}' does not support the 'Reset' action.".format(member_resp.dict.get("Id", member)),
                )
        except Exception as err:
            sut.add_test_result(
                CAT_NAME, test_name, operation, "FAIL", "Failed to get the chassis '{}' ({}).".format(member, err)
            )

    logger.log_use_case_test_footer(CAT_NAME, test_name)
    return chassis


def get_advertised_reset_types(sut: SystemUnderTest, reset_action: dict):
    """
    Reads the advertised allowable reset types from a Reset action

    Args:
        sut: The system under test
        reset_action: The Reset action property from the resource

    Returns:
        The advertised allowable reset types, or None if not advertised
    """

    reset_types = reset_action.get("ResetType@Redfish.AllowableValues")
    if reset_types is None and "@Redfish.ActionInfo" in reset_action:
        action_info = sut.session.get(reset_action["@Redfish.ActionInfo"])
        redfish_utilities.verify_response(action_info)
        for param in action_info.dict.get("Parameters", []):
            if param["Name"] == "ResetType":
                reset_types = param.get("AllowableValues")
    return reset_types


def check_advertised_reset_types(sut: SystemUnderTest, test_name: str, chassis_id: str, reset_types: list):
    """
    Adds the test result for the reset types a chassis advertises

    A generic client cannot act on an advertised value the Resource schema
    does not define.

    Args:
        sut: The system under test
        test_name: The name of the test
        chassis_id: The identifier of the chassis
        reset_types: The advertised allowable reset types
    """

    operation = "Checking the advertised reset types for chassis '{}'".format(chassis_id)
    undefined_types = sorted(set(reset_types) - RESET_TYPE_VALUES)
    if len(undefined_types) != 0:
        sut.add_test_result(
            CAT_NAME,
            test_name,
            operation,
            "FAIL",
            "Chassis '{}' advertises 'ResetType' allowable value(s) {}; the Resource schema does not define these values.".format(
                chassis_id, undefined_types
            ),
        )
    else:
        sut.add_test_result(CAT_NAME, test_name, operation, "PASS")


def chassis_power_test_reset_type(sut: SystemUnderTest, chassis: list):
    """
    Performs the chassis reset type test

    Args:
        sut: The system under test
        chassis: The chassis to test

    Returns:
        A dictionary of reset capabilities for each chassis
    """

    test_name = TEST_RESET_TYPE[0]
    logger.log_use_case_test_header(CAT_NAME, test_name)
    reset_capabilities = {}

    for member in chassis:
        operation = "Getting supported reset types for chassis '{}'".format(member["Id"])
        logger.logger.info(operation)

        reset_action = member["Actions"]["#Chassis.Reset"]
        try:
            reset_types = get_advertised_reset_types(sut, reset_action)
            if reset_types is None:
                sut.add_test_result(
                    CAT_NAME,
                    test_name,
                    operation,
                    "FAILWARN",
                    "Chassis '{}' does not report supported reset types.".format(member["Id"]),
                )
            else:
                reset_capabilities[member["Id"]] = reset_types
                sut.add_test_result(CAT_NAME, test_name, operation, "PASS")
                check_advertised_reset_types(sut, test_name, member["Id"], reset_types)
        except Exception as err:
            sut.add_test_result(
                CAT_NAME,
                test_name,
                operation,
                "FAIL",
                "Failed to get the reset types supported for chassis '{}' ({}).".format(member["Id"], err),
            )

    logger.log_use_case_test_footer(CAT_NAME, test_name)
    return reset_capabilities


def check_sampled_states(sampled_states):
    """
    Splits sampled 'Status.State' values into schema-defined and undefined values

    Args:
        sampled_states: The list of sampled 'Status.State' values; None entries,
                        from resources that omit 'Status', are ignored

    Returns:
        A sorted list of the sampled values the Resource schema does not define
    """

    return sorted(set(sampled_states) - RESOURCE_STATE_VALUES - {None})


def add_sampled_states_result(sut, cat_name, test_name, resource_kind, resource_id, reset_type, sampled_states):
    """
    Adds the test result for the health states a resource reported while resetting

    Args:
        sut: The system under test
        cat_name: The name of the test category
        test_name: The name of the test
        resource_kind: The kind of resource monitored, such as 'Chassis' or 'System'
        resource_id: The identifier of the resource monitored
        reset_type: The reset type performed
        sampled_states: The list of sampled 'Status.State' values
    """

    operation = "Checking the health states {} '{}' reported while resetting".format(resource_kind.lower(), resource_id)
    undefined_states = check_sampled_states(sampled_states)
    if len(undefined_states) != 0:
        sut.add_test_result(
            cat_name,
            test_name,
            operation,
            "FAIL",
            "{} '{}' reported 'Status.State' value(s) {} during a reset of type '{}'; the Resource schema does not define these values.".format(
                resource_kind, resource_id, undefined_states, reset_type
            ),
        )
    else:
        sut.add_test_result(cat_name, test_name, operation, "PASS")


def reset_chassis(sut: SystemUnderTest, test_name: str, member: dict, reset_type: str):
    """
    Performs the reset action on a chassis

    Args:
        sut: The system under test
        test_name: The name of the test
        member: The chassis to reset
        reset_type: The reset type to request

    Returns:
        True if the service accepted the reset request
    """

    operation = "Performing the reset action with the reset type '{}' for chassis '{}'".format(reset_type, member["Id"])
    logger.logger.info(operation)
    try:
        response = sut.session.post(member["Actions"]["#Chassis.Reset"]["target"], body={"ResetType": reset_type})
        response = redfish_utilities.poll_task_monitor(sut.session, response, silent=True)
        redfish_utilities.verify_response(response)
        sut.add_test_result(CAT_NAME, test_name, operation, "PASS")
        return True
    except Exception as err:
        sut.add_test_result(
            CAT_NAME,
            test_name,
            operation,
            "FAILWARN",
            "Failed to reset chassis '{}' ({}).".format(member["Id"], err),
        )
        return False


def poll_chassis_power(sut: SystemUnderTest, member: dict, expected_power_state):
    """
    Polls the power state of a chassis after a reset

    A chassis that drops its management controller mid-reset is retried until
    the timeout rather than failed.

    Args:
        sut: The system under test
        member: The chassis to poll
        expected_power_state: The power state that ends the polling, or None

    Returns:
        A tuple of the last chassis response, or None if never reachable, and
        the list of sampled 'Status.State' values
    """

    sampled_states = []
    chassis_info = None
    # Poll the power state for up to 50 seconds
    for i in range(0, 10):
        logger.logger.debug("Monitoring check {}".format(i))
        try:
            chassis_info = sut.session.get(member["@odata.id"])
            redfish_utilities.verify_response(chassis_info)
        except Exception as err:
            logger.logger.info("Chassis '{}' not reachable during reset ({}); retrying".format(member["Id"], err))
            time.sleep(5)
            continue
        sampled_states.append(chassis_info.dict.get("Status", {}).get("State"))
        if chassis_info.dict["PowerState"] == expected_power_state:
            break
        time.sleep(5)
    return chassis_info, sampled_states


def add_power_state_result(sut, test_name, operation, member, reset_type, expected_power_state, chassis_info):
    """
    Adds the test result for the power state monitoring of a chassis

    Args:
        sut: The system under test
        test_name: The name of the test
        operation: The operation being reported
        member: The chassis monitored
        reset_type: The reset type performed
        expected_power_state: The expected end power state, or None
        chassis_info: The last chassis response, or None if never reachable
    """

    if chassis_info is None:
        sut.add_test_result(
            CAT_NAME,
            test_name,
            operation,
            "FAIL",
            "Chassis '{}' was not reachable after performing a reset of type '{}'.".format(member["Id"], reset_type),
        )
        return

    logger.logger.info(
        "Finished monitoring the power state for chassis '{}'; 'PowerState' contains '{}'".format(
            member["Id"], chassis_info.dict["PowerState"]
        )
    )
    if expected_power_state is None:
        sut.add_test_result(
            CAT_NAME,
            test_name,
            operation,
            "SKIP",
            "No expected power state can be derived for reset type '{}'; chassis '{}' remained reachable and reports 'PowerState' '{}'.".format(
                reset_type, member["Id"], chassis_info.dict["PowerState"]
            ),
        )
    elif chassis_info.dict["PowerState"] != expected_power_state:
        sut.add_test_result(
            CAT_NAME,
            test_name,
            operation,
            "FAIL",
            "Chassis '{}' did not transition to the '{}' power state after performing a reset of type '{}'.".format(
                member["Id"], expected_power_state, reset_type
            ),
        )
    else:
        sut.add_test_result(CAT_NAME, test_name, operation, "PASS")


def run_chassis_reset_case(sut: SystemUnderTest, test_name: str, member: dict, reset_type: str):
    """
    Resets a chassis with one reset type and monitors the outcome

    Args:
        sut: The system under test
        test_name: The name of the test
        member: The chassis to test
        reset_type: The reset type to request
    """

    if not reset_chassis(sut, test_name, member, reset_type):
        return

    # Wait for the chassis to reset
    time.sleep(10)

    operation = "Monitoring the power state of chassis '{}'".format(member["Id"])
    logger.logger.info(operation)

    # Skip if the chassis does not support reporting the power state
    if "PowerState" not in member:
        sut.add_test_result(
            CAT_NAME,
            test_name,
            operation,
            "SKIP",
            "Chassis '{}' does not support the 'PowerState' property.".format(member["Id"]),
        )
        return

    # An advertised type outside the schema's vocabulary already failed the
    # reset type test, and no end state can be derived from it; the chassis
    # is still monitored so its health states are checked
    expected_power_state = None
    if reset_type in RESET_TYPE_VALUES:
        expected_power_state = "Off" if reset_type in OFF_RESET_TYPES else "On"

    try:
        chassis_info, sampled_states = poll_chassis_power(sut, member, expected_power_state)
        add_power_state_result(sut, test_name, operation, member, reset_type, expected_power_state, chassis_info)
        if chassis_info is not None:
            add_sampled_states_result(sut, CAT_NAME, test_name, "Chassis", member["Id"], reset_type, sampled_states)
    except Exception as err:
        sut.add_test_result(
            CAT_NAME,
            test_name,
            operation,
            "FAIL",
            "Failed to monitor the power state for chassis '{}' ({}).".format(member["Id"], err),
        )


def chassis_power_test_reset_operation(sut: SystemUnderTest, chassis: list, reset_capabilities: dict):
    """
    Performs the chassis reset operation test

    Args:
        sut: The system under test
        chassis: The chassis to test
        reset_capabilities: The reset capabilities for each chassis
    """

    test_name = TEST_RESET_OPERATION[0]
    logger.log_use_case_test_header(CAT_NAME, test_name)

    for member in chassis:
        # Skip if the chassis does not show reset capabilities
        if member["Id"] not in reset_capabilities:
            operation = "Performing the reset action for chassis '{}'".format(member["Id"])
            sut.add_test_result(
                CAT_NAME,
                test_name,
                operation,
                "SKIP",
                "Chassis '{}' does not show supported reset types.".format(member["Id"]),
            )
            continue

        # Test each reset type the chassis advertises
        for reset_type in reset_capabilities[member["Id"]]:
            run_chassis_reset_case(sut, test_name, member, reset_type)

    logger.log_use_case_test_footer(CAT_NAME, test_name)
